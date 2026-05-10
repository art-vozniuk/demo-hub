import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { v4 as uuidv4 } from "uuid";
import { ArrowLeft, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import UploadDropzone from "@/components/UploadDropzone";
import GenerationCard from "@/components/GenerationCard";
import {
  generativeApi,
  pipelinesApi,
  type GenerativePresetRead,
  type GenerativeEditingResult,
  type PipelineStatusItem,
} from "@/api";
import { uploadToS3, getFileExtension } from "@/lib/s3";
import { useAnalytics } from "@/hooks/useAnalytics";
import { toast } from "sonner";

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 240_000;

const GenerativeEditingGenerate = () => {
  const navigate = useNavigate();
  const { track } = useAnalytics();
  const [searchParams] = useSearchParams();
  const presetSlug = searchParams.get("preset") ?? "";

  const [preset, setPreset] = useState<GenerativePresetRead | null>(null);
  const [presetError, setPresetError] = useState<string | null>(null);

  const [photo, setPhoto] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadedRef, setUploadedRef] = useState<{
    bucket: string;
    key: string;
  } | null>(null);

  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [pipelineStatus, setPipelineStatus] =
    useState<PipelineStatusItem | null>(null);
  const [estimatedFinishAt, setEstimatedFinishAt] = useState<string | null>(
    null
  );
  const [workersMissing, setWorkersMissing] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const pollIntervalRef = useRef<number | null>(null);
  const pollTimeoutRef = useRef<number | null>(null);
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
        if (item.status === "FAILED") {
          setErrorMessage(item.message ?? "Generation failed");
        }
      }
    } catch (err) {
      if (!isMountedRef.current) return;
      console.error(err);
      setErrorMessage("Failed to poll status. Try again later.");
      clearPolling();
      setIsProcessing(false);
    }
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!preset || !uploadedRef) return;

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

      await pipelinesApi.queuePipelines({
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
      });

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
  }, [preset, uploadedRef, track, pollOnce]);

  const handleReplacePhoto = () => {
    setPhoto(null);
    setUploadedRef(null);
    setPipelineId(null);
    setPipelineStatus(null);
    setErrorMessage(null);
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
  const canGenerate =
    !isProcessing && !!uploadedRef && !isUploading && !pipelineId;

  return (
    <main className="container mx-auto px-6 py-12 space-y-10 min-h-[calc(100vh-8rem)]">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => navigate("/generative-editing")}
        className="gap-1"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to presets
      </Button>

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
                  <div className="absolute inset-0 flex items-center justify-center bg-background/70 text-sm">
                    Uploading…
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

          <div className="flex justify-center">
            <Button
              size="lg"
              disabled={!canGenerate}
              onClick={handleGenerate}
              className="hover-glow text-base font-semibold px-10 py-5 shadow-elegant"
            >
              <Sparkles className="mr-2 h-5 w-5" />
              {isUploading
                ? "Uploading…"
                : isProcessing
                  ? "Generating…"
                  : "Generate"}
            </Button>
          </div>
        </div>

        <div className="space-y-4">
          <GenerationCard
            imageUrl={preset.preview_image_url}
            isProcessing={isProcessing}
            generatedImage={resultUrl ?? undefined}
            errorMessage={pipelineStatus?.status === "FAILED" ? errorMessage : undefined}
            templateName={null}
            pipelineId={pipelineId}
            estimatedFinishAt={estimatedFinishAt}
            workersMissing={workersMissing}
          />

          <div className="space-y-2">
            <h1 className="text-3xl font-bold tracking-tight">{preset.title}</h1>
            {preset.description && (
              <p className="text-muted-foreground leading-relaxed">
                {preset.description}
              </p>
            )}
          </div>
        </div>
      </section>
    </main>
  );
};

export default GenerativeEditingGenerate;
