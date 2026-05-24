// One-at-a-time generation session for the 3D editor: prompt → flux-t2i
// → user confirm → sharp → splat. Pipelines run via pipelinesApi; Editor
// wires onSplatReady to actually insert the resulting splat into the scene.

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { v4 as uuidv4 } from "uuid";
import { toast } from "sonner";

import {
  pipelinesApi,
  ApiError,
  type PipelineStatusItem,
  type FluxResult,
  type SharpResult,
} from "@/api";
import { parseS3Url } from "@/lib/s3";
import { useWallet } from "@/contexts/WalletContext";
import { useAnalytics } from "@/hooks/useAnalytics";

const T2I_PIPELINE = "generative_t2i";
// Iteration runs through klein (the existing edit-focused pipeline) —
// schnell's img2img is lower quality and exposes a confusing strength knob.
const ITERATE_PIPELINE = "generative_editing_custom";
const SHARP_PIPELINE = "sharp";
const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 240_000;
const ITERATE_STEPS = 4;

// Flux-t2i result, augmented with bucket+key so Sharp can chain off it.
export interface T2IImage {
  result_url: string;
  image_bucket: string;
  image_key: string;
  width?: number;
  height?: number;
  seed?: number | null;
}

export type GenerationPhase =
  | "idle"
  | "flux-pending"
  | "flux-ready"
  | "sharp-pending"
  | "failed";

export interface GenerationSessionState {
  phase: GenerationPhase;
  prompt: string;
  image: T2IImage | null;
  iterating: boolean;
  fluxPipelineId: string | null;
  sharpPipelineId: string | null;
  splatName: string | null;
  errorMessage: string | null;
  errorPhase: "flux" | "sharp" | null;
  estimatedFinishAt: string | null;
  workersMissing: boolean;
}

interface StartArgs {
  prompt: string;
  iterate?: boolean;
}

export interface GenerationSessionApi extends GenerationSessionState {
  fluxCost: number | undefined;
  iterateCost: number | undefined;
  sharpCost: number | undefined;
  totalCost: number | undefined;
  start: (args: StartArgs) => Promise<void>;
  confirm: () => Promise<void>;
  cancel: () => void;
  reset: () => void;
}

interface ProviderProps {
  children: ReactNode;
  outputBucket?: string;
  onSplatReady: (args: { url: string; name: string }) => void;
}

const GenerationSessionContext = createContext<GenerationSessionApi | undefined>(
  undefined,
);

const INITIAL_STATE: GenerationSessionState = {
  phase: "idle",
  prompt: "",
  image: null,
  iterating: false,
  fluxPipelineId: null,
  sharpPipelineId: null,
  splatName: null,
  errorMessage: null,
  errorPhase: null,
  estimatedFinishAt: null,
  workersMissing: false,
};

function slugifyPrompt(prompt: string): string {
  const words = prompt
    .toLowerCase()
    .replace(/[^a-z0-9\s]+/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 5);
  return words.length > 0 ? words.join("-") : "generated-splat";
}

export const GenerationSessionProvider = ({
  children,
  outputBucket = "media",
  onSplatReady,
}: ProviderProps) => {
  const { balance, getCost, refresh: refreshBalance } = useWallet();
  const { track } = useAnalytics();

  const [state, setState] = useState<GenerationSessionState>(INITIAL_STATE);

  const fluxPollRef = useRef<number | null>(null);
  const fluxTimeoutRef = useRef<number | null>(null);
  const sharpPollRef = useRef<number | null>(null);
  const sharpTimeoutRef = useRef<number | null>(null);
  // setInterval keeps spawning polls without awaiting the previous one,
  // so multiple in-flight pollSharp/pollFlux can all see COMPLETED at
  // once. Track which pipeline_ids we've already handled to drop dupes.
  const processedPipelinesRef = useRef<Set<string>>(new Set());
  // Refed so the poll callbacks don't need to re-subscribe when Editor re-renders.
  const onSplatReadyRef = useRef(onSplatReady);
  useEffect(() => {
    onSplatReadyRef.current = onSplatReady;
  }, [onSplatReady]);

  const clearFluxPolling = useCallback(() => {
    if (fluxPollRef.current !== null) {
      window.clearInterval(fluxPollRef.current);
      fluxPollRef.current = null;
    }
    if (fluxTimeoutRef.current !== null) {
      window.clearTimeout(fluxTimeoutRef.current);
      fluxTimeoutRef.current = null;
    }
  }, []);
  const clearSharpPolling = useCallback(() => {
    if (sharpPollRef.current !== null) {
      window.clearInterval(sharpPollRef.current);
      sharpPollRef.current = null;
    }
    if (sharpTimeoutRef.current !== null) {
      window.clearTimeout(sharpTimeoutRef.current);
      sharpTimeoutRef.current = null;
    }
  }, []);
  useEffect(
    () => () => {
      clearFluxPolling();
      clearSharpPolling();
    },
    [clearFluxPolling, clearSharpPolling],
  );

  const reset = useCallback(() => {
    clearFluxPolling();
    clearSharpPolling();
    setState(INITIAL_STATE);
  }, [clearFluxPolling, clearSharpPolling]);

  const cancel = useCallback(() => {
    // No Modal-side abort — we just stop polling. Already-debited tokens stay debited.
    clearFluxPolling();
    clearSharpPolling();
    setState((prev) => {
      if (prev.phase === "idle") return prev;
      track({
        name: "editor_generate_splat_cancelled",
        params: { phase: prev.phase },
      });
      return INITIAL_STATE;
    });
  }, [clearFluxPolling, clearSharpPolling, track]);

  const onSharpComplete = useCallback(
    (item: PipelineStatusItem, name: string) => {
      const result = item.result as SharpResult | undefined;
      if (!result?.result_url) {
        toast.error("Sharp returned no splat URL.");
        setState((prev) => ({
          ...prev,
          phase: "failed",
          errorPhase: "sharp",
          errorMessage: "Sharp returned no splat URL.",
        }));
        return;
      }
      track({
        name: "editor_generate_splat_sharp_completed",
        params: { pipeline_id: item.id },
      });
      onSplatReadyRef.current({ url: result.result_url, name });
      reset();
    },
    [reset, track],
  );

  const pollSharp = useCallback(
    async (pipelineId: string, name: string) => {
      if (processedPipelinesRef.current.has(pipelineId)) return;
      try {
        const resp = await pipelinesApi.getStatus([pipelineId]);
        const item = resp.pipelines.find((p) => p.id === pipelineId);
        if (!item) return;
        if (item.status === "COMPLETED" || item.status === "FAILED") {
          if (processedPipelinesRef.current.has(pipelineId)) return;
          processedPipelinesRef.current.add(pipelineId);
        }
        if (item.status === "COMPLETED") {
          clearSharpPolling();
          onSharpComplete(item, name);
        } else if (item.status === "FAILED") {
          clearSharpPolling();
          refreshBalance();
          const msg = item.message || "Splat generation failed.";
          toast.error(msg);
          track({
            name: "editor_generate_splat_sharp_failed",
            params: { pipeline_id: pipelineId, error: msg },
          });
          setState((prev) => ({
            ...prev,
            phase: "failed",
            errorPhase: "sharp",
            errorMessage: msg,
          }));
        }
      } catch (err) {
        console.error("sharp poll failed:", err);
      }
    },
    [clearSharpPolling, onSharpComplete, refreshBalance, track],
  );

  const startSharp = useCallback(
    async (image: T2IImage, name: string) => {
      const pipelineId = uuidv4();
      const traceId = uuidv4();
      try {
        await pipelinesApi.queuePipelines({
          trace_id: traceId,
          jobs: [
            {
              pipeline_id: pipelineId,
              pipeline_name: SHARP_PIPELINE,
              input: {
                image_bucket: image.image_bucket,
                image_key: image.image_key,
              },
            },
          ],
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 402) {
          await refreshBalance();
          toast.error("Out of tokens for splat generation.");
        } else {
          toast.error(`Failed to queue splat: ${err}`);
        }
        setState((prev) => ({
          ...prev,
          phase: "failed",
          errorPhase: "sharp",
          errorMessage: String(err),
        }));
        return;
      }
      refreshBalance();
      track({
        name: "editor_generate_splat_sharp_started",
        params: { pipeline_id: pipelineId },
      });
      setState((prev) => ({
        ...prev,
        phase: "sharp-pending",
        sharpPipelineId: pipelineId,
        splatName: name,
        errorMessage: null,
        errorPhase: null,
        estimatedFinishAt: null,
        workersMissing: false,
      }));
      pipelinesApi
        .getEstimate(pipelineId)
        .then((res) => {
          setState((prev) =>
            prev.sharpPipelineId === pipelineId
              ? {
                  ...prev,
                  estimatedFinishAt: new Date(
                    Date.now() + res.estimated_seconds * 1000,
                  ).toISOString(),
                  workersMissing: res.workers_missing,
                }
              : prev,
          );
        })
        .catch((e) => console.warn("sharp estimate fetch failed:", e));
      pollSharp(pipelineId, name);
      sharpPollRef.current = window.setInterval(() => {
        pollSharp(pipelineId, name);
      }, POLL_INTERVAL_MS);
      sharpTimeoutRef.current = window.setTimeout(() => {
        clearSharpPolling();
        toast.error("Splat generation timed out.");
        setState((prev) => ({
          ...prev,
          phase: "failed",
          errorPhase: "sharp",
          errorMessage: "Sharp generation timed out.",
        }));
      }, POLL_TIMEOUT_MS);
    },
    [clearSharpPolling, pollSharp, refreshBalance, track],
  );

  const pollFlux = useCallback(
    async (pipelineId: string) => {
      if (processedPipelinesRef.current.has(pipelineId)) return;
      try {
        const resp = await pipelinesApi.getStatus([pipelineId]);
        const item = resp.pipelines.find((p) => p.id === pipelineId);
        if (!item) return;
        if (item.status === "COMPLETED" || item.status === "FAILED") {
          if (processedPipelinesRef.current.has(pipelineId)) return;
          processedPipelinesRef.current.add(pipelineId);
        }
        if (item.status === "COMPLETED") {
          clearFluxPolling();
          const result = item.result as
            | (FluxResult & {
                image_bucket?: string;
                image_key?: string;
                width?: number;
                height?: number;
                seed?: number | null;
              })
            | undefined;
          if (!result?.result_url) {
            toast.error("Image generation returned an incomplete result.");
            setState((prev) => ({
              ...prev,
              phase: "failed",
              errorPhase: "flux",
              errorMessage: "Image generation returned an incomplete result.",
            }));
            return;
          }
          // Klein returns only {result_url}; schnell adds bucket+key. Parse
          // the URL when missing so Sharp always has somewhere to read from.
          let imageBucket = result.image_bucket;
          let imageKey = result.image_key;
          if (!imageBucket || !imageKey) {
            try {
              const parsed = parseS3Url(result.result_url);
              imageBucket = parsed.bucket;
              imageKey = parsed.key;
            } catch (err) {
              toast.error(`Could not parse image URL: ${err}`);
              setState((prev) => ({
                ...prev,
                phase: "failed",
                errorPhase: "flux",
                errorMessage: String(err),
              }));
              return;
            }
          }
          track({
            name: "editor_generate_splat_flux_completed",
            params: { pipeline_id: pipelineId },
          });
          setState((prev) => ({
            ...prev,
            phase: "flux-ready",
            image: {
              result_url: result.result_url,
              image_bucket: imageBucket!,
              image_key: imageKey!,
              width: result.width,
              height: result.height,
              seed: result.seed ?? null,
            },
          }));
        } else if (item.status === "FAILED") {
          clearFluxPolling();
          refreshBalance();
          const msg = item.message || "Image generation failed.";
          toast.error(msg);
          track({
            name: "editor_generate_splat_flux_failed",
            params: { pipeline_id: pipelineId, error: msg },
          });
          setState((prev) => ({
            ...prev,
            phase: "failed",
            errorPhase: "flux",
            errorMessage: msg,
          }));
        }
      } catch (err) {
        console.error("flux poll failed:", err);
      }
    },
    [clearFluxPolling, refreshBalance, track],
  );

  const start = useCallback(
    async ({ prompt, iterate = false }: StartArgs) => {
      const trimmed = prompt.trim();
      if (!trimmed) {
        toast.error("Please enter a prompt.");
        return;
      }
      if (
        state.phase === "flux-pending" ||
        state.phase === "sharp-pending"
      ) {
        toast.error("A generation is already in progress.");
        return;
      }
      const useInit = iterate && state.image !== null;
      const initImage = useInit ? state.image : null;

      const pipelineId = uuidv4();
      const traceId = uuidv4();
      const pipelineName = initImage ? ITERATE_PIPELINE : T2I_PIPELINE;
      const input: Record<string, unknown> = initImage
        ? {
            image_bucket: initImage.image_bucket,
            image_key: initImage.image_key,
            prompt: trimmed,
            num_inference_steps: ITERATE_STEPS,
          }
        : {
            prompt: trimmed,
            output_bucket: outputBucket,
          };

      setState((prev) => ({
        ...prev,
        phase: "flux-pending",
        prompt: trimmed,
        iterating: !!initImage,
        fluxPipelineId: pipelineId,
        sharpPipelineId: null,
        splatName: null,
        errorMessage: null,
        errorPhase: null,
        estimatedFinishAt: null,
        workersMissing: false,
        // Keep the previous image visible behind the spinner when iterating.
        image: initImage ? prev.image : null,
      }));

      try {
        await pipelinesApi.queuePipelines({
          trace_id: traceId,
          jobs: [
            {
              pipeline_id: pipelineId,
              pipeline_name: pipelineName,
              input,
            },
          ],
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 402) {
          await refreshBalance();
          toast.error("Out of tokens.");
        } else {
          toast.error(`Failed to queue: ${err}`);
        }
        setState((prev) => ({ ...prev, phase: "idle", fluxPipelineId: null }));
        return;
      }
      refreshBalance();
      track({
        name: "editor_generate_splat_flux_submitted",
        params: {
          pipeline_id: pipelineId,
          has_init_image: !!initImage,
        },
      });
      pipelinesApi
        .getEstimate(pipelineId)
        .then((res) => {
          setState((prev) =>
            prev.fluxPipelineId === pipelineId
              ? {
                  ...prev,
                  estimatedFinishAt: new Date(
                    Date.now() + res.estimated_seconds * 1000,
                  ).toISOString(),
                  workersMissing: res.workers_missing,
                }
              : prev,
          );
        })
        .catch((e) => console.warn("flux estimate fetch failed:", e));
      pollFlux(pipelineId);
      fluxPollRef.current = window.setInterval(
        () => pollFlux(pipelineId),
        POLL_INTERVAL_MS,
      );
      fluxTimeoutRef.current = window.setTimeout(() => {
        clearFluxPolling();
        toast.error("Image generation timed out.");
        setState((prev) => ({
          ...prev,
          phase: "failed",
          errorPhase: "flux",
          errorMessage: "Flux generation timed out.",
        }));
      }, POLL_TIMEOUT_MS);
    },
    [
      state.phase,
      state.image,
      outputBucket,
      clearFluxPolling,
      pollFlux,
      refreshBalance,
      track,
    ],
  );

  const confirm = useCallback(async () => {
    if (state.phase !== "flux-ready" || !state.image) {
      toast.error("No image to confirm.");
      return;
    }
    const sharpCost = getCost(SHARP_PIPELINE);
    if (balance !== null && sharpCost !== undefined && balance < sharpCost) {
      toast.error("Not enough tokens for splat generation.");
      return;
    }
    const name = slugifyPrompt(state.prompt);
    track({
      name: "editor_generate_splat_confirmed",
      params: { name },
    });
    await startSharp(state.image, name);
  }, [
    state.phase,
    state.image,
    state.prompt,
    balance,
    getCost,
    startSharp,
    track,
  ]);

  const fluxCost = getCost(T2I_PIPELINE);
  const iterateCost = getCost(ITERATE_PIPELINE);
  const sharpCost = getCost(SHARP_PIPELINE);
  const totalCost =
    fluxCost !== undefined && sharpCost !== undefined
      ? fluxCost + sharpCost
      : undefined;

  return (
    <GenerationSessionContext.Provider
      value={{
        ...state,
        fluxCost,
        iterateCost,
        sharpCost,
        totalCost,
        start,
        confirm,
        cancel,
        reset,
      }}
    >
      {children}
    </GenerationSessionContext.Provider>
  );
};

export const useGenerationSession = (): GenerationSessionApi => {
  const ctx = useContext(GenerationSessionContext);
  if (!ctx) {
    throw new Error(
      "useGenerationSession must be used within a GenerationSessionProvider",
    );
  }
  return ctx;
};
