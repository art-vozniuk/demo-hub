/**
 * One-at-a-time generation session for the 3D editor.
 *
 * Two-phase state machine: Flux T2I/I2I generates an image, user
 * confirms or iterates, then Sharp turns the chosen image into a splat.
 * Both phases survive the overlay being closed — a viewport badge keeps
 * the session reachable in the background.
 *
 * The session owns pipeline orchestration only; the Editor wires the
 * `onSplatReady` callback to actually insert the resulting splat into
 * the scene.
 */

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
import { useWallet } from "@/contexts/WalletContext";
import { useAnalytics } from "@/hooks/useAnalytics";

const FLUX_PIPELINE = "generative_t2i";
const SHARP_PIPELINE = "sharp";
const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 240_000;

// Result of a flux-t2i generation. Augmented over the bare FluxResult
// type because we need bucket+key to chain into Sharp.
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
  // Last prompt used (so the overlay can show it during pending and
  // pre-fill it for the next iteration).
  prompt: string;
  // Last generated image; set during flux-ready and kept around through
  // sharp-pending so the overlay can keep showing it.
  image: T2IImage | null;
  // Whether the latest flux call was an iteration on a previous image.
  // Used by analytics + UI.
  iterating: boolean;
  // Active flux or sharp pipeline ids, for badge text + cancellation.
  fluxPipelineId: string | null;
  sharpPipelineId: string | null;
  // Slugified prompt used as the placeholder + final object name.
  splatName: string | null;
  errorMessage: string | null;
  errorPhase: "flux" | "sharp" | null;
}

interface StartArgs {
  prompt: string;
  // When true, use the current image as init for img2img iteration.
  // Caller is expected to only set this when an image is already loaded.
  iterate?: boolean;
  strength?: number;
}

export interface GenerationSessionApi extends GenerationSessionState {
  // Public costs (token amounts), derived from /me/balance.
  fluxCost: number | undefined;
  sharpCost: number | undefined;
  totalCost: number | undefined;
  start: (args: StartArgs) => Promise<void>;
  confirm: () => Promise<void>;
  cancel: () => void;
  reset: () => void;
}

interface ProviderProps {
  children: ReactNode;
  // Where flux-t2i should upload the generated image. Sharp will read
  // from the same bucket, so this also doubles as the sharp input
  // bucket. Defaults to "media" to match the editor's existing assets.
  outputBucket?: string;
  // Called once the Sharp pipeline produces a .splat file. The Editor
  // wires this to fetch the bytes and post `editor-load-splat` to the
  // renderer iframe.
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
};

function slugifyPrompt(prompt: string): string {
  // Take up to first 5 words, alpha-numeric only, kebab-case. Fallback
  // to "generated-splat" so we never end up with an empty name.
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

  // Polling timers per phase. We keep them in refs (not state) so the
  // poll callbacks see live values without re-subscribing.
  const fluxPollRef = useRef<number | null>(null);
  const fluxTimeoutRef = useRef<number | null>(null);
  const sharpPollRef = useRef<number | null>(null);
  const sharpTimeoutRef = useRef<number | null>(null);
  // Always-fresh reference to onSplatReady; the prop changes identity
  // each render in the Editor and we don't want to tear down polling
  // every time.
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
  // Tear down all polling on unmount so navigating away doesn't leak.
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
    // Cancel from any active phase. We don't try to abort the Modal job —
    // tokens for flux are already debited; this just stops us from
    // polling the result. The user has been warned by the overlay.
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
      try {
        const resp = await pipelinesApi.getStatus([pipelineId]);
        const item = resp.pipelines.find((p) => p.id === pipelineId);
        if (!item) return;
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
      }));
      // Kick first poll immediately so a fast-warm Sharp doesn't wait
      // the full interval.
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
      try {
        const resp = await pipelinesApi.getStatus([pipelineId]);
        const item = resp.pipelines.find((p) => p.id === pipelineId);
        if (!item) return;
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
          if (
            !result?.result_url ||
            !result?.image_bucket ||
            !result?.image_key
          ) {
            toast.error("Image generation returned an incomplete result.");
            setState((prev) => ({
              ...prev,
              phase: "failed",
              errorPhase: "flux",
              errorMessage: "Image generation returned an incomplete result.",
            }));
            return;
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
              image_bucket: result.image_bucket!,
              image_key: result.image_key!,
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
    async ({ prompt, iterate = false, strength = 0.8 }: StartArgs) => {
      const trimmed = prompt.trim();
      if (!trimmed) {
        toast.error("Please enter a prompt.");
        return;
      }
      // Refuse to start a second concurrent session. Editor disables
      // the button too, but this is the defensive check.
      if (
        state.phase === "flux-pending" ||
        state.phase === "sharp-pending"
      ) {
        toast.error("A generation is already in progress.");
        return;
      }
      // Iteration needs a prior image. If the caller asked to iterate
      // without one (shouldn't happen via UI), fall back to T2I.
      const useInit = iterate && state.image !== null;
      const initImage = useInit ? state.image : null;

      const pipelineId = uuidv4();
      const traceId = uuidv4();
      const input: Record<string, unknown> = {
        prompt: trimmed,
        output_bucket: outputBucket,
      };
      if (initImage) {
        input.init_image_bucket = initImage.image_bucket;
        input.init_image_key = initImage.image_key;
        input.strength = strength;
      }

      // Optimistically flip to flux-pending so the UI shows the spinner
      // immediately — we revert on submit failure.
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
        // Keep the previous image visible behind the spinner while
        // iterating; clear it for a fresh T2I run so we don't show
        // stale content.
        image: initImage ? prev.image : null,
      }));

      try {
        await pipelinesApi.queuePipelines({
          trace_id: traceId,
          jobs: [
            {
              pipeline_id: pipelineId,
              pipeline_name: FLUX_PIPELINE,
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

  const fluxCost = getCost(FLUX_PIPELINE);
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
