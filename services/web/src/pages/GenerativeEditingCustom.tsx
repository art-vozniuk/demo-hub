import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { v4 as uuidv4 } from "uuid";
import { ArrowLeft, ImagePlus, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import UploadDropzone from "@/components/UploadDropzone";
import GenerationCard from "@/components/GenerationCard";
import CostBadge from "@/components/CostBadge";
import {
  pipelinesApi,
  ApiError,
  type GenerativeEditingResult,
  type PipelineStatusItem,
} from "@/api";
import { uploadToS3, getFileExtension } from "@/lib/s3";
import { useAnalytics } from "@/hooks/useAnalytics";
import { useWallet } from "@/contexts/WalletContext";
import { useAuth } from "@/contexts/AuthContext";
import OutOfTokensDialog from "@/components/OutOfTokensDialog";
import { toast } from "sonner";

const PIPELINE_NAME = "generative_editing_custom";
const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 240_000;

type Quality = "fast" | "standard" | "high";

const QUALITY_STEPS: Record<Quality, number> = {
  fast: 2,
  standard: 4,
  high: 8,
};

// Multipliers mirror services/core/migrations/.../014_*.py — Fast/Std/High.
// Shown to the user so the Quality dropdown is honest about the cost
// tradeoff; the server re-resolves authoritatively at charge time.
const QUALITY_MULTIPLIER_LABEL: Record<Quality, string> = {
  fast: "×0.7",
  standard: "×1",
  high: "×1.5",
};

const GenerativeEditingCustom = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { track } = useAnalytics();

  const { user, loading: authLoading } = useAuth();
  const { balance, getCost, refresh: refreshBalance } = useWallet();
  const baseCost = getCost(PIPELINE_NAME);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      navigate(
        `/auth?redirect=${encodeURIComponent(location.pathname + location.search)}`,
        { replace: true },
      );
    }
  }, [authLoading, user, navigate, location.pathname, location.search]);

  const [outOfTokensDialogOpen, setOutOfTokensDialogOpen] = useState(false);

  const [photo, setPhoto] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadedRef, setUploadedRef] = useState<{
    bucket: string;
    key: string;
  } | null>(null);

  const [prompt, setPrompt] = useState("");
  const [quality, setQuality] = useState<Quality>("standard");

  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [pipelineStatus, setPipelineStatus] =
    useState<PipelineStatusItem | null>(null);
  const [estimatedFinishAt, setEstimatedFinishAt] = useState<string | null>(
    null,
  );
  const [workersMissing, setWorkersMissing] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const pollIntervalRef = useRef<number | null>(null);
  const pollTimeoutRef = useRef<number | null>(null);
  const isMountedRef = useRef(true);

  // One stable object URL per chosen file. We render the same URL in two
  // places (the side preview and the GenerationCard background), so we
  // can't lazily create-on-read — that would revoke the URL out from
  // under the previous <img>.
  const [previewUrl, setPreviewUrl] = useState<string>("");
  useEffect(() => {
    if (!photo) {
      setPreviewUrl("");
      return;
    }
    const url = URL.createObjectURL(photo);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      clearPolling();
    };
  }, []);

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

  const pollOnce = useCallback(
    async (id: string) => {
      if (!isMountedRef.current) return;
      try {
        const resp = await pipelinesApi.getStatus([id]);
        const item = resp.pipelines[0];
        if (!item || !isMountedRef.current) return;
        setPipelineStatus(item);

        if (item.status === "COMPLETED" || item.status === "FAILED") {
          setIsProcessing(false);
          clearPolling();
          // FAILED triggers a refund server-side; pull the credit back into
          // the UI without a page reload.
          if (item.status === "FAILED") refreshBalance();
        }
      } catch (err) {
        if (!isMountedRef.current) return;
        console.error(err);
        setErrorMessage("Failed to poll status. Try again later.");
        clearPolling();
        setIsProcessing(false);
      }
    },
    [refreshBalance],
  );

  // Final cost comes from the server (POST /pipelines/cost-preview); we
  // bump a token on every Quality change and ignore stale responses so
  // a slow earlier request can't overwrite a newer one. Local Math
  // mirror would risk drifting from backend handlers.
  const [finalCost, setFinalCost] = useState<number | undefined>(undefined);
  const previewTokenRef = useRef(0);
  useEffect(() => {
    const token = ++previewTokenRef.current;
    pipelinesApi
      .previewCost({
        pipeline_name: PIPELINE_NAME,
        input: { num_inference_steps: QUALITY_STEPS[quality] },
      })
      .then((res) => {
        if (previewTokenRef.current !== token) return;
        setFinalCost(res.cost);
      })
      .catch((err) => {
        if (previewTokenRef.current !== token) return;
        console.warn("cost preview failed:", err);
        // Fall back to base while preview is unavailable — server
        // remains authoritative at charge time, so the user just sees
        // the conservative price.
        setFinalCost(baseCost);
      });
  }, [quality, baseCost]);

  const handleGenerate = useCallback(async () => {
    if (!uploadedRef) return;
    if (finalCost === undefined) return;
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) {
      toast.error("Please enter a prompt");
      return;
    }

    if (balance !== null && balance < finalCost) {
      setOutOfTokensDialogOpen(true);
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
        name: "generative_custom_generate_started",
        params: {
          pipeline_id: newPipelineId,
          quality,
          prompt_length: trimmedPrompt.length,
        },
      });

      try {
        await pipelinesApi.queuePipelines({
          trace_id: traceId,
          jobs: [
            {
              pipeline_id: newPipelineId,
              pipeline_name: PIPELINE_NAME,
              input: {
                image_bucket: uploadedRef.bucket,
                image_key: uploadedRef.key,
                prompt: trimmedPrompt,
                num_inference_steps: QUALITY_STEPS[quality],
              },
            },
          ],
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 402) {
          await refreshBalance();
          setOutOfTokensDialogOpen(true);
          setIsProcessing(false);
          return;
        }
        throw err;
      }

      refreshBalance();
      setPipelineId(newPipelineId);

      pipelinesApi
        .getEstimate(newPipelineId)
        .then((res) => {
          if (!isMountedRef.current) return;
          setEstimatedFinishAt(
            new Date(Date.now() + res.estimated_seconds * 1000).toISOString(),
          );
          setWorkersMissing(res.workers_missing);
        })
        .catch((e) => console.warn("estimate fetch failed:", e));

      await pollOnce(newPipelineId);
      pollIntervalRef.current = window.setInterval(
        () => pollOnce(newPipelineId),
        POLL_INTERVAL_MS,
      );
      pollTimeoutRef.current = window.setTimeout(() => {
        clearPolling();
        setIsProcessing(false);
        setErrorMessage(
          "Generation timed out. The serverless GPU may be cold-starting; please try again.",
        );
      }, POLL_TIMEOUT_MS);
    } catch (err) {
      console.error(err);
      toast.error(`Failed to queue: ${err}`);
      setIsProcessing(false);
      setPipelineId(null);
    }
  }, [
    uploadedRef,
    prompt,
    quality,
    finalCost,
    balance,
    refreshBalance,
    track,
    pollOnce,
  ]);

  const handleReplacePhoto = () => {
    setPhoto(null);
    setUploadedRef(null);
    setPipelineId(null);
    setPipelineStatus(null);
    setEstimatedFinishAt(null);
    setWorkersMissing(false);
    setErrorMessage(null);
    clearPolling();
  };

  const resultUrl = (
    pipelineStatus?.result as GenerativeEditingResult | undefined
  )?.result_url;

  const canGenerate =
    !isProcessing &&
    !!uploadedRef &&
    !isUploading &&
    !pipelineId &&
    prompt.trim().length > 0;

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
            Your own prompt
          </h1>
          {baseCost !== undefined && <CostBadge cost={baseCost} />}
        </div>
        <p className="text-muted-foreground leading-relaxed max-w-3xl">
          Skip the cinematic presets — drop in any photo and describe the edit
          yourself. Same FLUX.2 klein backend, just with a free-form prompt.
        </p>
      </header>

      <section className="max-w-5xl mx-auto grid gap-8 lg:grid-cols-2 items-start">
        <div className="space-y-6">
          {!photo ? (
            <UploadDropzone onFileSelect={setPhoto} selectedFile={photo} />
          ) : (
            <div className="space-y-3">
              <div className="aspect-square rounded-xl overflow-hidden border border-border bg-muted/20 relative">
                <img
                  src={previewUrl}
                  alt="Your photo"
                  className="w-full h-full object-cover"
                />
                {isUploading && (
                  <div className="absolute inset-0 flex items-center justify-center bg-background/80">
                    <div className="text-center">
                      <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-primary border-r-transparent mb-2" />
                      <p className="text-sm text-muted-foreground">
                        Uploading…
                      </p>
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

          <div className="space-y-2">
            <Label htmlFor="custom-prompt">Prompt</Label>
            <Textarea
              id="custom-prompt"
              placeholder="e.g. cinematic portrait, golden hour, shallow depth of field"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={isProcessing || !!pipelineId}
              rows={4}
              className="resize-none"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="custom-quality">Quality</Label>
            <Select
              value={quality}
              onValueChange={(v) => setQuality(v as Quality)}
              disabled={isProcessing || !!pipelineId}
            >
              <SelectTrigger id="custom-quality">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fast">
                  Fast · 2 steps · {QUALITY_MULTIPLIER_LABEL.fast}
                </SelectItem>
                <SelectItem value="standard">
                  Standard · 4 steps · {QUALITY_MULTIPLIER_LABEL.standard}
                </SelectItem>
                <SelectItem value="high">
                  High · 8 steps · {QUALITY_MULTIPLIER_LABEL.high}
                </SelectItem>
              </SelectContent>
            </Select>
            {finalCost !== undefined && (
              <p className="text-xs text-muted-foreground">
                Final cost: <span className="font-medium text-foreground">{finalCost}</span> token{finalCost === 1 ? "" : "s"}
              </p>
            )}
          </div>

          {errorMessage && !pipelineId && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {errorMessage}
            </div>
          )}
        </div>

        <div className="space-y-4">
          {previewUrl ? (
            <GenerationCard
              imageUrl={previewUrl}
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
          ) : (
            // No photo yet → show a placeholder tile that matches the
            // generation card's aspect ratio so the layout doesn't jump
            // when the upload lands. Avoids the broken-image icon a
            // bare <img src=""/> would produce.
            <div className="aspect-square rounded-xl border-2 border-dashed border-border bg-muted/10 flex flex-col items-center justify-center gap-3 text-center p-6">
              <div className="rounded-full bg-muted p-4">
                <ImagePlus className="h-6 w-6 text-muted-foreground" />
              </div>
              <p className="text-sm text-muted-foreground max-w-[16rem]">
                Your result appears here once you upload a photo and run a prompt.
              </p>
            </div>
          )}

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
        </div>
      </section>

      <OutOfTokensDialog
        open={outOfTokensDialogOpen}
        onOpenChange={setOutOfTokensDialogOpen}
      />
    </main>
  );
};

export default GenerativeEditingCustom;
