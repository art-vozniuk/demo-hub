// One-at-a-time generation session for the 3D editor: prompt → flux-t2i
// → user confirm → 3D pipeline → asset in scene. The 3D stage is one of
// two pipelines selected by `outputKind`: GLB mesh (trellis, default) or
// gaussian splat (sharp). Stage 1 (FLUX text→image) is identical for both.
// Editor wires onAssetReady to insert the resulting asset into the scene.

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
} from "@/api";
import { parseS3Url } from "@/lib/s3";
import { useWallet } from "@/contexts/WalletContext";
import { useAnalytics } from "@/hooks/useAnalytics";

const T2I_PIPELINE = "generative_t2i";
// Iteration runs through klein (the existing edit-focused pipeline) —
// schnell's img2img is lower quality and exposes a confusing strength knob.
const ITERATE_PIPELINE = "generative_editing_custom";
// Stage 2 — the image→3D pipelines the output toggle picks between.
const MESH_PIPELINE = "trellis";
const SPLAT_PIPELINE = "sharp";
const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 240_000;
const ITERATE_STEPS = 4;

// What the second stage produces. "glb" → trellis mesh, "splat" → sharp.
export type OutputKind = "glb" | "splat";

// The asset kind the editor renderer expects, derived from OutputKind.
export type AssetKind = "mesh" | "splat";

function stage2Pipeline(kind: OutputKind): string {
  return kind === "glb" ? MESH_PIPELINE : SPLAT_PIPELINE;
}

function assetKindFor(kind: OutputKind): AssetKind {
  return kind === "glb" ? "mesh" : "splat";
}

// Flux-t2i result, augmented with bucket+key so stage 2 can chain off it.
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
  | "object-pending"
  | "failed";

export interface GenerationSessionState {
  phase: GenerationPhase;
  outputKind: OutputKind;
  prompt: string;
  image: T2IImage | null;
  iterating: boolean;
  fluxPipelineId: string | null;
  objectPipelineId: string | null;
  objectName: string | null;
  errorMessage: string | null;
  errorPhase: "flux" | "object" | null;
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
  objectCost: number | undefined;
  totalCost: number | undefined;
  setOutputKind: (kind: OutputKind) => void;
  start: (args: StartArgs) => Promise<void>;
  confirm: () => Promise<void>;
  cancel: () => void;
  reset: () => void;
}

interface ProviderProps {
  children: ReactNode;
  outputBucket?: string;
  onAssetReady: (args: { url: string; name: string; kind: AssetKind }) => void;
}

const GenerationSessionContext = createContext<GenerationSessionApi | undefined>(
  undefined,
);

const INITIAL_STATE: GenerationSessionState = {
  phase: "idle",
  outputKind: "glb",
  prompt: "",
  image: null,
  iterating: false,
  fluxPipelineId: null,
  objectPipelineId: null,
  objectName: null,
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
  return words.length > 0 ? words.join("-") : "generated-object";
}

export const GenerationSessionProvider = ({
  children,
  outputBucket = "media",
  onAssetReady,
}: ProviderProps) => {
  const { balance, getCost, refresh: refreshBalance } = useWallet();
  const { track } = useAnalytics();

  const [state, setState] = useState<GenerationSessionState>(INITIAL_STATE);

  const fluxPollRef = useRef<number | null>(null);
  const fluxTimeoutRef = useRef<number | null>(null);
  const objectPollRef = useRef<number | null>(null);
  const objectTimeoutRef = useRef<number | null>(null);
  // setInterval keeps spawning polls without awaiting the previous one,
  // so multiple in-flight pollObject/pollFlux can all see COMPLETED at
  // once. Track which pipeline_ids we've already handled to drop dupes.
  const processedPipelinesRef = useRef<Set<string>>(new Set());
  // Refed so the poll callbacks don't need to re-subscribe when Editor re-renders.
  const onAssetReadyRef = useRef(onAssetReady);
  useEffect(() => {
    onAssetReadyRef.current = onAssetReady;
  }, [onAssetReady]);

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
  const clearObjectPolling = useCallback(() => {
    if (objectPollRef.current !== null) {
      window.clearInterval(objectPollRef.current);
      objectPollRef.current = null;
    }
    if (objectTimeoutRef.current !== null) {
      window.clearTimeout(objectTimeoutRef.current);
      objectTimeoutRef.current = null;
    }
  }, []);
  useEffect(
    () => () => {
      clearFluxPolling();
      clearObjectPolling();
    },
    [clearFluxPolling, clearObjectPolling],
  );

  const reset = useCallback(() => {
    clearFluxPolling();
    clearObjectPolling();
    setState(INITIAL_STATE);
  }, [clearFluxPolling, clearObjectPolling]);

  const setOutputKind = useCallback((kind: OutputKind) => {
    setState((prev) => (prev.outputKind === kind ? prev : { ...prev, outputKind: kind }));
  }, []);

  const cancel = useCallback(() => {
    // No Modal-side abort — we just stop polling. Already-debited tokens stay debited.
    clearFluxPolling();
    clearObjectPolling();
    setState((prev) => {
      if (prev.phase === "idle") return prev;
      track({
        name: "editor_generate_splat_cancelled",
        params: { phase: prev.phase },
      });
      // Preserve the chosen output kind across a cancel so the toggle
      // doesn't snap back to the default mid-session.
      return { ...INITIAL_STATE, outputKind: prev.outputKind };
    });
  }, [clearFluxPolling, clearObjectPolling, track]);

  const onObjectComplete = useCallback(
    (item: PipelineStatusItem, name: string, kind: OutputKind) => {
      const result = item.result as { result_url?: string } | undefined;
      if (!result?.result_url) {
        toast.error("3D generation returned no result URL.");
        setState((prev) => ({
          ...prev,
          phase: "failed",
          errorPhase: "object",
          errorMessage: "3D generation returned no result URL.",
        }));
        return;
      }
      track({
        name: "editor_generate_splat_sharp_completed",
        params: { pipeline_id: item.id, output_kind: kind },
      });
      onAssetReadyRef.current({
        url: result.result_url,
        name,
        kind: assetKindFor(kind),
      });
      reset();
    },
    [reset, track],
  );

  const pollObject = useCallback(
    async (pipelineId: string, name: string, kind: OutputKind) => {
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
          clearObjectPolling();
          onObjectComplete(item, name, kind);
        } else if (item.status === "FAILED") {
          clearObjectPolling();
          refreshBalance();
          const msg = item.message || "3D generation failed.";
          toast.error(msg);
          track({
            name: "editor_generate_splat_sharp_failed",
            params: { pipeline_id: pipelineId, error: msg, output_kind: kind },
          });
          setState((prev) => ({
            ...prev,
            phase: "failed",
            errorPhase: "object",
            errorMessage: msg,
          }));
        }
      } catch (err) {
        console.error("object poll failed:", err);
      }
    },
    [clearObjectPolling, onObjectComplete, refreshBalance, track],
  );

  const startObject = useCallback(
    async (image: T2IImage, name: string, kind: OutputKind) => {
      const pipelineId = uuidv4();
      const traceId = uuidv4();
      try {
        await pipelinesApi.queuePipelines({
          trace_id: traceId,
          jobs: [
            {
              pipeline_id: pipelineId,
              pipeline_name: stage2Pipeline(kind),
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
          toast.error("Out of tokens for 3D generation.");
        } else {
          toast.error(`Failed to queue 3D generation: ${err}`);
        }
        setState((prev) => ({
          ...prev,
          phase: "failed",
          errorPhase: "object",
          errorMessage: String(err),
        }));
        return;
      }
      refreshBalance();
      track({
        name: "editor_generate_splat_sharp_started",
        params: { pipeline_id: pipelineId, output_kind: kind },
      });
      setState((prev) => ({
        ...prev,
        phase: "object-pending",
        objectPipelineId: pipelineId,
        objectName: name,
        errorMessage: null,
        errorPhase: null,
        estimatedFinishAt: null,
        workersMissing: false,
      }));
      pipelinesApi
        .getEstimate(pipelineId)
        .then((res) => {
          setState((prev) =>
            prev.objectPipelineId === pipelineId
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
        .catch((e) => console.warn("object estimate fetch failed:", e));
      pollObject(pipelineId, name, kind);
      objectPollRef.current = window.setInterval(() => {
        pollObject(pipelineId, name, kind);
      }, POLL_INTERVAL_MS);
      objectTimeoutRef.current = window.setTimeout(() => {
        clearObjectPolling();
        toast.error("3D generation timed out.");
        setState((prev) => ({
          ...prev,
          phase: "failed",
          errorPhase: "object",
          errorMessage: "3D generation timed out.",
        }));
      }, POLL_TIMEOUT_MS);
    },
    [clearObjectPolling, pollObject, refreshBalance, track],
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
          // the URL when missing so stage 2 always has somewhere to read from.
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
        state.phase === "object-pending"
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
        objectPipelineId: null,
        objectName: null,
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
    const cost = getCost(stage2Pipeline(state.outputKind));
    if (balance !== null && cost !== undefined && balance < cost) {
      toast.error("Not enough tokens for 3D generation.");
      return;
    }
    const name = slugifyPrompt(state.prompt);
    track({
      name: "editor_generate_splat_confirmed",
      params: { name, output_kind: state.outputKind },
    });
    await startObject(state.image, name, state.outputKind);
  }, [
    state.phase,
    state.image,
    state.prompt,
    state.outputKind,
    balance,
    getCost,
    startObject,
    track,
  ]);

  const fluxCost = getCost(T2I_PIPELINE);
  const iterateCost = getCost(ITERATE_PIPELINE);
  const objectCost = getCost(stage2Pipeline(state.outputKind));
  const totalCost =
    fluxCost !== undefined && objectCost !== undefined
      ? fluxCost + objectCost
      : undefined;

  return (
    <GenerationSessionContext.Provider
      value={{
        ...state,
        fluxCost,
        iterateCost,
        objectCost,
        totalCost,
        setOutputKind,
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
