import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { v4 as uuidv4 } from "uuid";
import { Sparkles } from "lucide-react";
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
import { DemoHeader } from "@/components/DemoHeader";
import UploadDropzone from "@/components/UploadDropzone";
import GenerationCard from "@/components/GenerationCard";
import {
  pipelinesApi,
  ApiError,
  type FluxResult,
  type PipelineStatusItem,
} from "@/api";
import { uploadToS3, getFileExtension } from "@/lib/s3";
import { useAnalytics } from "@/hooks/useAnalytics";
import { useWallet } from "@/contexts/WalletContext";
import { useAuth } from "@/contexts/AuthContext";
import OutOfTokensDialog from "@/components/OutOfTokensDialog";
import { toast } from "sonner";

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 240_000;

type Quality = "fast" | "standard" | "high";

const QUALITY_STEPS: Record<Quality, number> = {
  fast: 2,
  standard: 4,
  high: 8,
};

const Flux = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { track } = useAnalytics();

  const { user, loading: authLoading } = useAuth();
  const { balance, getCost, refresh: refreshBalance } = useWallet();
  const fluxCost = getCost("flux");

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

  const handleGenerate = useCallback(async () => {
    if (!uploadedRef) return;
    if (fluxCost === undefined) return;
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) {
      toast.error("Please enter a prompt");
      return;
    }

    if (balance !== null && balance < fluxCost) {
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
        name: "flux_generate_started",
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
              pipeline_name: "flux",
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
    fluxCost,
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
    pipelineStatus?.result as FluxResult | undefined
  )?.result_url;

  const canGenerate =
    !isProcessing &&
    !!uploadedRef &&
    !isUploading &&
    !pipelineId &&
    prompt.trim().length > 0;

  return (
    <main className="container mx-auto px-6 py-12 space-y-8 min-h-[calc(100vh-8rem)]">
      <DemoHeader
        title="Flux"
        cost={fluxCost}
        description="Direct access to FLUX.2 klein image-to-image editing on a serverless GPU. Drop in a photo, write any prompt — the same Modal app that powers Generative Editing, just without the preset gating."
        tagline={
          !photo ? "Upload a photo and describe the edit" : undefined
        }
      />

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
            <Label htmlFor="flux-prompt">Prompt</Label>
            <Textarea
              id="flux-prompt"
              placeholder="e.g. cinematic portrait, golden hour, shallow depth of field"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={isProcessing || !!pipelineId}
              rows={4}
              className="resize-none"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="flux-quality">Quality</Label>
            <Select
              value={quality}
              onValueChange={(v) => setQuality(v as Quality)}
              disabled={isProcessing || !!pipelineId}
            >
              <SelectTrigger id="flux-quality">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fast">Fast · 2 steps</SelectItem>
                <SelectItem value="standard">Standard · 4 steps</SelectItem>
                <SelectItem value="high">High · 8 steps</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Higher quality = more inference steps, longer wait.
            </p>
          </div>

          {errorMessage && !pipelineId && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {errorMessage}
            </div>
          )}
        </div>

        <div className="space-y-4">
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

export default Flux;
