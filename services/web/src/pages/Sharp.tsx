import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { v4 as uuidv4 } from "uuid";
import { Github, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DemoHeader } from "@/components/DemoHeader";
import { SplatViewer, type SplatViewerScene } from "@/components/SplatViewer";
import UploadDropzone from "@/components/UploadDropzone";
import {
  pipelinesApi,
  ApiError,
  type PipelineStatusItem,
  type SharpResult,
} from "@/api";
import { uploadToS3, getFileExtension } from "@/lib/s3";
import { useAnalytics } from "@/hooks/useAnalytics";
import { useWallet } from "@/contexts/WalletContext";
import { useAuth } from "@/contexts/AuthContext";
import OutOfTokensDialog from "@/components/OutOfTokensDialog";
import { toast } from "sonner";
import sharpDemoVideo from "@/assets/sharp-demo.mp4";

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 120_000;

const formatRemaining = (seconds: number): string => {
  if (seconds <= 1) return "<1s";
  if (seconds >= 60) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }
  return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
};

function resultToViewerScene(result: SharpResult): SplatViewerScene {
  return {
    slug: "sharp-result",
    title: "SHARP result",
    sceneUrl: result.result_url,
    cameraEye: result.camera_eye,
    cameraFwd: result.camera_fwd,
  };
}

const Sharp = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { track } = useAnalytics();

  const { user } = useAuth();
  const { balance, getCost, refresh: refreshBalance } = useWallet();
  const sharpCost = getCost("sharp");

  const [outOfTokensDialogOpen, setOutOfTokensDialogOpen] = useState(false);

  const [photo, setPhoto] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadedRef, setUploadedRef] = useState<{
    bucket: string;
    key: string;
  } | null>(null);

  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [pipelineStatus, setPipelineStatus] =
    useState<PipelineStatusItem | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [estimatedFinishAt, setEstimatedFinishAt] = useState<string | null>(
    null,
  );
  const [workersMissing, setWorkersMissing] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const pollIntervalRef = useRef<number | null>(null);
  const pollTimeoutRef = useRef<number | null>(null);
  const isMountedRef = useRef(true);

  // Stable preview URL for the local file; revoke on unmount or replace.
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
    if (!isProcessing || !estimatedFinishAt) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [isProcessing, estimatedFinishAt]);

  const remainingSeconds = (() => {
    if (!estimatedFinishAt) return null;
    const target = new Date(estimatedFinishAt).getTime();
    if (Number.isNaN(target)) return null;
    const diff = (target - now) / 1000;
    return diff > 0 ? diff : 0.01;
  })();

  // Reset uploadedRef when a new file is picked so we don't submit
  // the stale S3 key against the newly chosen photo.
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
          // FAILED triggers a server-side refund; pull it into the UI.
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

    if (!user) {
      navigate(
        `/auth?redirect=${encodeURIComponent(location.pathname + location.search)}`,
      );
      return;
    }

    if (sharpCost === undefined) return;

    if (balance !== null && balance < sharpCost) {
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
        name: "sharp_generate_started",
        params: { pipeline_id: newPipelineId },
      });

      try {
        await pipelinesApi.queuePipelines({
          trace_id: traceId,
          jobs: [
            {
              pipeline_id: newPipelineId,
              pipeline_name: "sharp",
              input: {
                image_bucket: uploadedRef.bucket,
                image_key: uploadedRef.key,
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
    user,
    sharpCost,
    balance,
    refreshBalance,
    track,
    pollOnce,
    navigate,
    location.pathname,
    location.search,
  ]);

  const handleReset = useCallback(() => {
    setPhoto(null);
    setUploadedRef(null);
    setPipelineId(null);
    setPipelineStatus(null);
    setErrorMessage(null);
    setIsProcessing(false);
    setEstimatedFinishAt(null);
    setWorkersMissing(false);
    clearPolling();
  }, []);

  const result =
    pipelineStatus?.status === "COMPLETED"
      ? (pipelineStatus.result as SharpResult | undefined)
      : null;
  const failed = pipelineStatus?.status === "FAILED";

  return (
    <main className="container mx-auto px-6 py-16 space-y-12 min-h-[calc(100vh-8rem)]">
      <DemoHeader
        title="SHARP"
        cost={sharpCost}
        description={
          <>
            Turn a single photo into a 3D Gaussian-Splatting scene you can
            orbit around in your browser. Wraps Apple's{" "}
            <a
              href="https://github.com/apple/ml-sharp"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              ml-sharp <Github className="h-3.5 w-3.5" />
            </a>{" "}
            feed-forward predictor on a serverless GPU.
          </>
        }
        tagline={
          !photo && !result && !failed ? "Drop a single photo" : undefined
        }
      />

      <section className="max-w-3xl mx-auto space-y-4">
        {!photo && !result && !failed && (
          <>
            <div className="group relative overflow-hidden rounded-xl border border-border shadow-elegant bg-card">
              <video
                src={sharpDemoVideo}
                autoPlay
                loop
                muted
                playsInline
                preload="auto"
                className="block w-full aspect-video object-cover"
              />
              <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent p-3">
                <p className="text-xs font-medium text-white/90">
                  Demo: photo → orbitable 3D scene
                </p>
              </div>
            </div>
            <UploadDropzone onFileSelect={setPhoto} selectedFile={photo} />
          </>
        )}

        {photo && !result && !failed && (
          <div className="space-y-4">
            <div className="group relative overflow-hidden rounded-xl border border-border shadow-elegant bg-card">
              <div className="aspect-square relative overflow-hidden">
                <img
                  src={previewUrl(photo)}
                  alt="Your photo"
                  className="h-full w-full object-cover transition-all duration-700"
                  style={{ filter: isProcessing ? "blur(30px)" : "none" }}
                />

                {isUploading && !isProcessing && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-background/40 backdrop-blur-sm gap-2">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                    <p className="text-white text-xs font-medium px-2 py-0.5 rounded bg-black/40">
                      Uploading…
                    </p>
                  </div>
                )}

                {isProcessing && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-background/10 backdrop-blur-sm gap-2">
                    <Loader2 className="h-8 w-8 animate-spin text-primary" />
                    {workersMissing ? (
                      <p className="text-white text-xs font-medium px-2 py-0.5 rounded bg-destructive/70 text-center max-w-[80%]">
                        No workers available for this pipeline
                      </p>
                    ) : remainingSeconds !== null ? (
                      <p className="text-white text-xs font-medium px-2 py-0.5 rounded bg-black/40">
                        ~{formatRemaining(remainingSeconds)} left
                      </p>
                    ) : (
                      <p className="text-white text-xs font-medium px-2 py-0.5 rounded bg-black/40">
                        {pipelineStatus?.status === "RUNNING"
                          ? "Running on GPU…"
                          : "Queued…"}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-center gap-3">
              <Button
                onClick={handleGenerate}
                disabled={!uploadedRef || isUploading || isProcessing}
              >
                {isUploading
                  ? "Uploading…"
                  : isProcessing
                    ? pipelineStatus?.status === "RUNNING"
                      ? "Running on GPU…"
                      : "Queued…"
                    : !user
                      ? "Sign in to generate"
                      : "Generate splat"}
              </Button>
              <Button
                variant="outline"
                onClick={handleReset}
                disabled={isProcessing}
              >
                Reset
              </Button>
            </div>
          </div>
        )}

        {errorMessage && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            {errorMessage}
          </div>
        )}

        {failed && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            Generation failed: {pipelineStatus?.message ?? "unknown error"}
            <div className="mt-3">
              <Button variant="outline" size="sm" onClick={handleReset}>
                Try another photo
              </Button>
            </div>
          </div>
        )}

        {result && (
          <div className="flex flex-col gap-3">
            <SplatViewer scene={resultToViewerScene(result)} height="60vh" />
            <div className="flex flex-wrap items-center justify-center gap-3 text-xs text-muted-foreground">
              <span>
                {result.gaussian_count?.toLocaleString() ?? "?"} gaussians
              </span>
              <span>•</span>
              <a
                href={result.result_url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:underline"
              >
                Download .splat
              </a>
              <span>•</span>
              <Button
                size="sm"
                variant="outline"
                onClick={handleReset}
                className="h-7"
              >
                Try another photo
              </Button>
            </div>
          </div>
        )}
      </section>

      <OutOfTokensDialog
        open={outOfTokensDialogOpen}
        onOpenChange={setOutOfTokensDialogOpen}
      />
    </main>
  );
};

export default Sharp;
