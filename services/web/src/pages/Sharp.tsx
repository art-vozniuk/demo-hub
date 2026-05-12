import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { v4 as uuidv4 } from "uuid";
import { ArrowLeft, Boxes, Github } from "lucide-react";
import { Button } from "@/components/ui/button";
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
import CostBadge from "@/components/CostBadge";
import OutOfTokensDialog from "@/components/OutOfTokensDialog";
import { toast } from "sonner";

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 120_000;
const RENDERER_URL = import.meta.env.VITE_RENDERER_URL as string | undefined;

/** Build the WASM viewer iframe URL for a transient SHARP result.
 * scene_url/eye/fwd are the same query params Renderer.tsx uses for
 * catalog scenes; here they point at the pipeline's .splat in S3. */
function buildResultIframeSrc(result: SharpResult): string {
  if (!RENDERER_URL) return "";
  const url = new URL(RENDERER_URL, window.location.origin);
  url.searchParams.set("scene", `sharp-result`);
  url.searchParams.set("scene_url", result.result_url);
  url.searchParams.set("eye", result.camera_eye.join(","));
  url.searchParams.set("fwd", result.camera_fwd.join(","));
  return url.toString();
}

const Sharp = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { track } = useAnalytics();

  const { user, loading: authLoading } = useAuth();
  const { balance, getCost, refresh: refreshBalance } = useWallet();
  const sharpCost = getCost("sharp");

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

  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [pipelineStatus, setPipelineStatus] =
    useState<PipelineStatusItem | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const pollIntervalRef = useRef<number | null>(null);
  const pollTimeoutRef = useRef<number | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      clearPolling();
    };
  }, []);

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
    if (sharpCost === undefined) return;

    if (balance !== null && balance < sharpCost) {
      setOutOfTokensDialogOpen(true);
      return;
    }

    setIsProcessing(true);
    setErrorMessage(null);
    setPipelineStatus(null);

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
  }, [uploadedRef, sharpCost, balance, refreshBalance, track, pollOnce]);

  const handleReset = useCallback(() => {
    setPhoto(null);
    setUploadedRef(null);
    setPipelineId(null);
    setPipelineStatus(null);
    setErrorMessage(null);
    setIsProcessing(false);
    clearPolling();
  }, []);

  const result =
    pipelineStatus?.status === "COMPLETED"
      ? (pipelineStatus.result as SharpResult | undefined)
      : null;
  const failed = pipelineStatus?.status === "FAILED";

  return (
    <div className="container mx-auto px-3 py-6 sm:px-6 sm:py-10">
      <div className="mb-6 flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate("/generative-editing")}
          className="gap-1"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <h1 className="flex items-center gap-2 text-2xl font-bold sm:text-3xl">
          <Boxes className="h-6 w-6 text-primary" />
          SHARP
        </h1>
        <CostBadge cost={sharpCost} />
      </div>

      <p className="mb-6 max-w-3xl text-sm text-muted-foreground sm:text-base">
        Turn a single photo into a 3D Gaussian-Splatting scene you can fly a
        camera around in your browser. Wraps Apple's{" "}
        <a
          href="https://github.com/apple/ml-sharp"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-primary hover:underline"
        >
          ml-sharp <Github className="h-3.5 w-3.5" />
        </a>{" "}
        feed-forward predictor on a serverless A10G — the model hallucinates
        backside geometry from a single view, so straight-on or 3/4 product
        shots work best.
      </p>

      {!result && !failed && (
        <div className="mb-4 max-w-3xl">
          <UploadDropzone onFileSelect={setPhoto} selectedFile={photo} />
        </div>
      )}

      {photo && !result && !failed && (
        <div className="mb-4 flex max-w-3xl flex-wrap items-center gap-3">
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
      )}

      {errorMessage && (
        <div className="mb-4 max-w-3xl rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {errorMessage}
        </div>
      )}

      {failed && (
        <div className="mb-4 max-w-3xl rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          Generation failed: {pipelineStatus?.message ?? "unknown error"}
          <div className="mt-3">
            <Button variant="outline" size="sm" onClick={handleReset}>
              Try another photo
            </Button>
          </div>
        </div>
      )}

      {result && RENDERER_URL && (
        <div className="flex flex-col gap-3">
          <div className="aspect-[4/3] w-full overflow-hidden rounded-lg border border-border bg-black sm:aspect-video">
            <iframe
              title="SHARP result"
              src={buildResultIframeSrc(result)}
              className="h-full w-full"
              allow="cross-origin-isolated"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
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

      <OutOfTokensDialog
        open={outOfTokensDialogOpen}
        onOpenChange={setOutOfTokensDialogOpen}
      />
    </div>
  );
};

export default Sharp;
