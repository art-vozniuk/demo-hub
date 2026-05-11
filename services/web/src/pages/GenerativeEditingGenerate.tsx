import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { v4 as uuidv4 } from "uuid";
import { ArrowLeft, Info, Sparkles, UserRoundCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import UploadDropzone from "@/components/UploadDropzone";
import GenerationCard from "@/components/GenerationCard";
import {
  generativeApi,
  pipelinesApi,
  ApiError,
  type GenerativePresetRead,
  type GenerativeEditingResult,
  type PipelineStatusItem,
} from "@/api";
import { uploadToS3, parseS3Url, getFileExtension } from "@/lib/s3";
import { useAnalytics } from "@/hooks/useAnalytics";
import { useWallet } from "@/contexts/WalletContext";
import { useTurnstile } from "@/hooks/useTurnstile";
import CostBadge from "@/components/CostBadge";
import InsufficientTokensDialog from "@/components/InsufficientTokensDialog";
import OutOfTokensDialog from "@/components/OutOfTokensDialog";
import { toast } from "sonner";

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 240_000;

const GenerativeEditingGenerate = () => {
  const navigate = useNavigate();
  const { track } = useAnalytics();
  const [searchParams] = useSearchParams();
  const presetSlug = searchParams.get("preset") ?? "";

  const {
    balance,
    isAnonymous,
    getCost,
    turnstileRequired,
    refresh: refreshBalance,
  } = useWallet();
  const fluxCost = getCost("generative_editing");
  const faceSwapCost = getCost("face_swap");
  // Mount Turnstile only when backend will actually check for the token.
  const turnstile = useTurnstile(isAnonymous === true && turnstileRequired);

  const [insufficientDialogOpen, setInsufficientDialogOpen] = useState(false);
  const [insufficientDialogCost, setInsufficientDialogCost] = useState(0);
  const [outOfTokensDialogOpen, setOutOfTokensDialogOpen] = useState(false);

  const [preset, setPreset] = useState<GenerativePresetRead | null>(null);
  const [presetError, setPresetError] = useState<string | null>(null);

  const [photo, setPhoto] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadedRef, setUploadedRef] = useState<{
    bucket: string;
    key: string;
  } | null>(null);

  // FLUX (generative_editing) pipeline state
  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [pipelineStatus, setPipelineStatus] =
    useState<PipelineStatusItem | null>(null);
  const [estimatedFinishAt, setEstimatedFinishAt] = useState<string | null>(
    null
  );
  const [workersMissing, setWorkersMissing] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Optional second pass: face_swap from user's photo onto the FLUX result
  // so the face actually looks like the subject. Lives in its own
  // pipeline state because the two pipelines run independently and we
  // want both results visible side-by-side at the end.
  const [refinePipelineId, setRefinePipelineId] = useState<string | null>(null);
  const [refinePipelineStatus, setRefinePipelineStatus] =
    useState<PipelineStatusItem | null>(null);
  const [refineEstimatedFinishAt, setRefineEstimatedFinishAt] = useState<
    string | null
  >(null);
  const [refineWorkersMissing, setRefineWorkersMissing] = useState(false);
  const [isRefining, setIsRefining] = useState(false);

  const pollIntervalRef = useRef<number | null>(null);
  const pollTimeoutRef = useRef<number | null>(null);
  const refinePollIntervalRef = useRef<number | null>(null);
  const refinePollTimeoutRef = useRef<number | null>(null);
  const isMountedRef = useRef(true);

  const objectUrlRef = useRef<string | null>(null);
  const previewUrl = (file: File) => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = URL.createObjectURL(file);
    return objectUrlRef.current;
  };

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    };
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      clearPolling();
      clearRefinePolling();
    };
  }, []);

  useEffect(() => {
    if (!presetSlug) {
      setPresetError("No preset selected.");
      return;
    }
    let alive = true;
    generativeApi
      .getPreset(presetSlug)
      .then((p) => {
        if (alive) setPreset(p);
      })
      .catch((err) => {
        if (alive) setPresetError(err?.message ?? "Preset not found");
      });
    return () => {
      alive = false;
    };
  }, [presetSlug]);

  useEffect(() => {
    if (!photo || uploadedRef) return;
    let alive = true;
    setIsUploading(true);
    setErrorMessage(null);

    (async () => {
      try {
        const id = uuidv4();
        const ext = getFileExtension(photo.name);
        const result = await uploadToS3(photo, "media", `user/${id}.${ext}`);
        if (alive) setUploadedRef({ bucket: result.bucket, key: result.key });
      } catch (err) {
        if (alive) {
          toast.error(`Upload failed: ${err}`);
          setPhoto(null);
        }
      } finally {
        if (alive) setIsUploading(false);
      }
    })();

    return () => {
      alive = false;
    };
  }, [photo, uploadedRef]);

  const clearPolling = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  };

  const clearRefinePolling = () => {
    if (refinePollIntervalRef.current) {
      clearInterval(refinePollIntervalRef.current);
      refinePollIntervalRef.current = null;
    }
    if (refinePollTimeoutRef.current) {
      clearTimeout(refinePollTimeoutRef.current);
      refinePollTimeoutRef.current = null;
    }
  };

  const pollOnce = useCallback(async (id: string) => {
    if (!isMountedRef.current) return;
    try {
      const resp = await pipelinesApi.getStatus([id]);
      const item = resp.pipelines[0];
      if (!item || !isMountedRef.current) return;
      setPipelineStatus(item);

      if (item.status === "COMPLETED" || item.status === "FAILED") {
        setIsProcessing(false);
        clearPolling();
        // FAILED triggers a refund server-side; pull it into the UI so
        // users see the credit return without a page reload.
        if (item.status === "FAILED") refreshBalance();
      }
    } catch (err) {
      if (!isMountedRef.current) return;
      console.error(err);
      setErrorMessage("Failed to poll status. Try again later.");
      clearPolling();
      setIsProcessing(false);
    }
  }, [refreshBalance]);

  const pollRefineOnce = useCallback(async (id: string) => {
    if (!isMountedRef.current) return;
    try {
      const resp = await pipelinesApi.getStatus([id]);
      const item = resp.pipelines[0];
      if (!item || !isMountedRef.current) return;
      setRefinePipelineStatus(item);

      if (item.status === "COMPLETED" || item.status === "FAILED") {
        setIsRefining(false);
        clearRefinePolling();
        if (item.status === "FAILED") refreshBalance();
      }
    } catch (err) {
      if (!isMountedRef.current) return;
      console.error(err);
      toast.error("Failed to poll face-match status. Try again later.");
      clearRefinePolling();
      setIsRefining(false);
    }
  }, [refreshBalance]);

  const handleGenerate = useCallback(async () => {
    if (!preset || !uploadedRef) return;
    if (fluxCost === undefined) return;

    // Pre-flight gate; server-side charge is still authoritative.
    if (balance !== null && balance < fluxCost) {
      if (isAnonymous) {
        setInsufficientDialogCost(fluxCost);
        setInsufficientDialogOpen(true);
      } else {
        setOutOfTokensDialogOpen(true);
      }
      return;
    }

    setIsProcessing(true);
    setErrorMessage(null);
    setPipelineStatus(null);
    setEstimatedFinishAt(null);
    setWorkersMissing(false);

    try {
      const traceId = uuidv4();
      const newPipelineId = uuidv4();

      track({
        name: "generative_generate_started",
        params: { preset_slug: preset.slug, pipeline_id: newPipelineId },
      });

      const turnstileToken = isAnonymous
        ? (await turnstile.getToken().catch(() => null)) ?? undefined
        : undefined;

      try {
        await pipelinesApi.queuePipelines(
          {
            trace_id: traceId,
            jobs: [
              {
                pipeline_id: newPipelineId,
                pipeline_name: "generative_editing",
                input: {
                  image_bucket: uploadedRef.bucket,
                  image_key: uploadedRef.key,
                  preset_slug: preset.slug,
                },
              },
            ],
          },
          turnstileToken,
        );
      } catch (err) {
        if (err instanceof ApiError && err.status === 402) {
          await refreshBalance();
          if (isAnonymous) {
            setInsufficientDialogCost(fluxCost);
            setInsufficientDialogOpen(true);
          } else {
            setOutOfTokensDialogOpen(true);
          }
          setIsProcessing(false);
          return;
        }
        throw err;
      }

      refreshBalance();
      setPipelineId(newPipelineId);

      // Fire one estimate request as soon as we have an id; capture the
      // result as a fixed finish-time the UI can count down against
      // (mirrors FaceFusionGenerate's approach so both demos use the
      // same heartbeat-driven ETA infrastructure).
      pipelinesApi
        .getEstimate(newPipelineId)
        .then((res) => {
          if (!isMountedRef.current) return;
          setEstimatedFinishAt(
            new Date(Date.now() + res.estimated_seconds * 1000).toISOString()
          );
          setWorkersMissing(res.workers_missing);
        })
        .catch((e) => console.warn("estimate fetch failed:", e));

      await pollOnce(newPipelineId);
      pollIntervalRef.current = window.setInterval(
        () => pollOnce(newPipelineId),
        POLL_INTERVAL_MS
      );
      pollTimeoutRef.current = window.setTimeout(() => {
        clearPolling();
        setIsProcessing(false);
        setErrorMessage(
          "Generation timed out. The serverless GPU may be cold-starting; please try again."
        );
      }, POLL_TIMEOUT_MS);
    } catch (err) {
      console.error(err);
      toast.error(`Failed to queue: ${err}`);
      setIsProcessing(false);
      setPipelineId(null);
    }
  }, [
    preset,
    uploadedRef,
    track,
    pollOnce,
    balance,
    isAnonymous,
    turnstile,
    refreshBalance,
    fluxCost,
  ]);

  const handleRefineFace = useCallback(async () => {
    if (!uploadedRef) return;
    if (faceSwapCost === undefined) return;
    const fluxResultUrl = (
      pipelineStatus?.result as GenerativeEditingResult | undefined
    )?.result_url;
    if (!fluxResultUrl) return;

    if (balance !== null && balance < faceSwapCost) {
      if (isAnonymous) {
        setInsufficientDialogCost(faceSwapCost);
        setInsufficientDialogOpen(true);
      } else {
        setOutOfTokensDialogOpen(true);
      }
      return;
    }

    let templateRef: { bucket: string; key: string };
    try {
      templateRef = parseS3Url(fluxResultUrl);
    } catch (err) {
      toast.error(`Cannot parse FLUX result URL: ${err}`);
      return;
    }

    // Mount the refine card synchronously so the user sees the source photo +
    // spinner immediately, instead of staring at an empty slot while Turnstile
    // and queueing run under the hood.
    const newRefineId = uuidv4();
    setRefinePipelineId(newRefineId);
    setIsRefining(true);
    setRefinePipelineStatus(null);
    setRefineEstimatedFinishAt(null);
    setRefineWorkersMissing(false);

    try {
      const traceId = uuidv4();

      track({
        name: "generative_refine_face_started",
        params: {
          preset_slug: preset?.slug ?? "",
          flux_pipeline_id: pipelineId ?? "",
          refine_pipeline_id: newRefineId,
        },
      });

      const turnstileToken = isAnonymous
        ? (await turnstile.getToken().catch(() => null)) ?? undefined
        : undefined;

      // Compute auto-detects the largest face on both source and target
      // when bboxes are omitted (see FaceSwapPipelineInput) — that's the
      // only sensible default here since there's no UI for face picking.
      try {
        await pipelinesApi.queuePipelines(
          {
            trace_id: traceId,
            jobs: [
              {
                pipeline_id: newRefineId,
                pipeline_name: "face_swap",
                input: {
                  source_image_bucket: uploadedRef.bucket,
                  source_image_key: uploadedRef.key,
                  template_image_bucket: templateRef.bucket,
                  template_image_key: templateRef.key,
                },
              },
            ],
          },
          turnstileToken,
        );
      } catch (err) {
        if (err instanceof ApiError && err.status === 402) {
          await refreshBalance();
          if (isAnonymous) {
            setInsufficientDialogCost(faceSwapCost);
            setInsufficientDialogOpen(true);
          } else {
            setOutOfTokensDialogOpen(true);
          }
          setIsRefining(false);
          setRefinePipelineId(null);
          return;
        }
        throw err;
      }

      refreshBalance();

      pipelinesApi
        .getEstimate(newRefineId)
        .then((res) => {
          if (!isMountedRef.current) return;
          setRefineEstimatedFinishAt(
            new Date(Date.now() + res.estimated_seconds * 1000).toISOString()
          );
          setRefineWorkersMissing(res.workers_missing);
        })
        .catch((e) => console.warn("refine estimate fetch failed:", e));

      await pollRefineOnce(newRefineId);
      refinePollIntervalRef.current = window.setInterval(
        () => pollRefineOnce(newRefineId),
        POLL_INTERVAL_MS
      );
      refinePollTimeoutRef.current = window.setTimeout(() => {
        clearRefinePolling();
        setIsRefining(false);
        toast.error("Face match timed out. Please try again.");
      }, POLL_TIMEOUT_MS);
    } catch (err) {
      console.error(err);
      toast.error(`Failed to queue face match: ${err}`);
      setIsRefining(false);
      setRefinePipelineId(null);
    }
  }, [
    uploadedRef,
    pipelineStatus,
    pipelineId,
    preset,
    track,
    pollRefineOnce,
    balance,
    isAnonymous,
    turnstile,
    refreshBalance,
    faceSwapCost,
  ]);

  const handleReplacePhoto = () => {
    setPhoto(null);
    setUploadedRef(null);
    setPipelineId(null);
    setPipelineStatus(null);
    setEstimatedFinishAt(null);
    setWorkersMissing(false);
    setRefinePipelineId(null);
    setRefinePipelineStatus(null);
    setRefineEstimatedFinishAt(null);
    setRefineWorkersMissing(false);
    setErrorMessage(null);
    clearPolling();
    clearRefinePolling();
  };

  if (presetError) {
    return (
      <main className="container mx-auto px-6 py-16 flex items-center justify-center min-h-[calc(100vh-8rem)]">
        <div className="text-center space-y-4">
          <h2 className="text-2xl font-bold">Preset unavailable</h2>
          <p className="text-muted-foreground">{presetError}</p>
          <Button
            onClick={() => navigate("/generative-editing")}
            variant="outline"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to presets
          </Button>
        </div>
      </main>
    );
  }

  if (!preset) {
    return (
      <main className="container mx-auto px-6 py-16 flex items-center justify-center min-h-[calc(100vh-8rem)]">
        <div className="text-muted-foreground">Loading preset…</div>
      </main>
    );
  }

  const resultUrl = (pipelineStatus?.result as
    | GenerativeEditingResult
    | undefined)?.result_url;
  const refineResultUrl = (refinePipelineStatus?.result as
    | { result_url?: string }
    | undefined)?.result_url;

  const canGenerate =
    !isProcessing && !!uploadedRef && !isUploading && !pipelineId;
  const fluxComplete = pipelineStatus?.status === "COMPLETED" && !!resultUrl;
  const canRefineFace =
    fluxComplete && !refinePipelineId && !isRefining;

  return (
    <main className="container mx-auto px-6 py-12 space-y-8 min-h-[calc(100vh-8rem)]">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => navigate("/generative-editing")}
        className="gap-1"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to presets
      </Button>

      <header className="max-w-5xl mx-auto space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
            {preset.title}
          </h1>
          {fluxCost !== undefined && <CostBadge cost={fluxCost} />}
        </div>
        {preset.description && (
          <p className="text-muted-foreground leading-relaxed max-w-3xl">
            {preset.description}
          </p>
        )}
      </header>

      <section className="max-w-5xl mx-auto grid gap-8 lg:grid-cols-2 items-start">
        <div className="space-y-6">
          {!photo ? (
            <UploadDropzone onFileSelect={setPhoto} selectedFile={photo} />
          ) : (
            <div className="space-y-3">
              <div className="aspect-square rounded-xl overflow-hidden border border-border bg-muted/20 relative">
                <img
                  src={previewUrl(photo)}
                  alt="Your photo"
                  className="w-full h-full object-cover"
                />
                {isUploading && (
                  <div className="absolute inset-0 flex items-center justify-center bg-background/80">
                    <div className="text-center">
                      <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-primary border-r-transparent mb-2" />
                      <p className="text-sm text-muted-foreground">Uploading…</p>
                    </div>
                  </div>
                )}
              </div>
              {!pipelineId && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleReplacePhoto}
                  disabled={isProcessing || isUploading}
                >
                  Replace photo
                </Button>
              )}
            </div>
          )}

          {errorMessage && !pipelineId && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {errorMessage}
            </div>
          )}
        </div>

        <div className="space-y-4">
          <GenerationCard
            imageUrl={preset.preview_image_url}
            isProcessing={isProcessing}
            generatedImage={resultUrl ?? undefined}
            errorMessage={
              pipelineStatus?.status === "FAILED"
                ? (pipelineStatus.message ?? "Generation failed")
                : undefined
            }
            templateName={null}
            pipelineId={pipelineId}
            estimatedFinishAt={estimatedFinishAt}
            workersMissing={workersMissing}
          />

          {!isProcessing && !pipelineId && (
            <div className="flex justify-center animate-fade-in">
              <Button
                size="lg"
                disabled={!canGenerate}
                onClick={handleGenerate}
                className="hover-glow text-base font-semibold px-10 py-5 shadow-elegant"
              >
                <Sparkles className="mr-2 h-5 w-5" />
                {isUploading ? "Uploading…" : "Generate"}
              </Button>
            </div>
          )}

          {canRefineFace && (
            <div className="flex justify-center items-center gap-2 flex-wrap">
              <Button
                onClick={handleRefineFace}
                variant="outline"
                size="sm"
                className="gap-2"
              >
                <UserRoundCheck className="h-4 w-4" />
                Match the face to your photo
              </Button>
              {faceSwapCost !== undefined && <CostBadge cost={faceSwapCost} />}
              <Popover>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    aria-label="What this does"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <Info className="h-4 w-4" />
                  </button>
                </PopoverTrigger>
                <PopoverContent
                  side="top"
                  className="max-w-xs w-auto p-3"
                >
                  <p className="text-xs leading-relaxed">
                    Can improve face recognizability, but may introduce
                    artifacts — especially on heavily stylized images.
                  </p>
                </PopoverContent>
              </Popover>
            </div>
          )}

          {refinePipelineId && resultUrl && (
            <GenerationCard
              imageUrl={resultUrl}
              isProcessing={isRefining}
              generatedImage={refineResultUrl ?? undefined}
              errorMessage={
                refinePipelineStatus?.status === "FAILED"
                  ? (refinePipelineStatus.message ?? "Face match failed")
                  : undefined
              }
              templateName={null}
              pipelineId={refinePipelineId}
              estimatedFinishAt={refineEstimatedFinishAt}
              workersMissing={refineWorkersMissing}
            />
          )}
        </div>
      </section>

      <InsufficientTokensDialog
        open={insufficientDialogOpen}
        onOpenChange={setInsufficientDialogOpen}
        cost={insufficientDialogCost}
        balance={balance ?? 0}
      />
      <OutOfTokensDialog
        open={outOfTokensDialogOpen}
        onOpenChange={setOutOfTokensDialogOpen}
      />
    </main>
  );
};

export default GenerativeEditingGenerate;
