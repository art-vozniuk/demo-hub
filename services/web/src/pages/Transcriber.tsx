// Transcriber demo: upload a recording → diarized transcript. The pipeline
// (Silero VAD → faster-whisper → pyannote) runs in a serverless GPU container —
// see services/modal/transcriber_pipeline; the platform side is the same async
// dispatch worker every other Modal demo uses.

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { v4 as uuidv4 } from "uuid";
import { Check, Copy, Github, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DemoHeader } from "@/components/DemoHeader";
import AudioDropzone from "@/components/AudioDropzone";
import OutOfTokensDialog from "@/components/OutOfTokensDialog";
import SharePipelineButton from "@/components/SharePipelineButton";
import TranscriptView from "@/components/transcriber/TranscriptView";
import { useTranscript } from "@/components/transcriber/useTranscript";
import {
  ApiError,
  pipelinesApi,
  type PipelineStatusItem,
  type TranscriberResult,
} from "@/api";
import { MAX_MEDIA_MINUTES, type MediaKind } from "@/lib/media";
import {
  getFileExtension,
  uploadMediaToS3,
  type UploadProgress,
} from "@/lib/s3";
import { useAnalytics } from "@/hooks/useAnalytics";
import { useAuth } from "@/contexts/AuthContext";
import { useWallet } from "@/contexts/WalletContext";

const POLL_INTERVAL_MS = 1500;
// The pipeline deadline for transcription is 1800s, and a video adds an
// extraction step plus a cold container on top; give up only well past that so
// the UI never abandons a run the backend is still finishing.
const POLL_TIMEOUT_MS = 2_400_000;

// Mirrors ALLOWED_MODELS / the cost multipliers in migration 021.
const MODELS = [
  { value: "medium", label: "medium · fastest", multiplier: "×0.75" },
  { value: "large-v3-turbo", label: "large-v3-turbo · balanced", multiplier: "×1" },
  { value: "large-v3", label: "large-v3 · best quality", multiplier: "×1.5" },
] as const;

const DEFAULT_MODEL = "large-v3-turbo";

// Mirrors ALLOWED_LANGUAGES in services/modal/transcriber/app.py.
const LANGUAGES = [
  { value: "auto", label: "Auto-detect" },
  { value: "ru", label: "Russian" },
  { value: "en", label: "English" },
  { value: "de", label: "German" },
  { value: "fr", label: "French" },
  { value: "es", label: "Spanish" },
  { value: "it", label: "Italian" },
  { value: "pt", label: "Portuguese" },
  { value: "pl", label: "Polish" },
  { value: "uk", label: "Ukrainian" },
  { value: "ja", label: "Japanese" },
  { value: "zh", label: "Chinese" },
  { value: "ko", label: "Korean" },
] as const;

const SPEAKER_CHOICES = ["auto", "2", "3", "4", "5", "6", "7", "8"] as const;

const formatRemaining = (seconds: number): string => {
  if (seconds <= 1) return "<1s";
  if (seconds >= 60) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }
  return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
};

const formatDuration = (seconds: number | null | undefined): string | null => {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return null;
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}m ${String(s).padStart(2, "0")}s`;
};

const Transcriber = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { track } = useAnalytics();
  const { user } = useAuth();
  const { balance, refresh: refreshBalance } = useWallet();

  const [audio, setAudio] = useState<File | null>(null);
  const [mediaKind, setMediaKind] = useState<MediaKind | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(
    null,
  );
  const [uploadedRef, setUploadedRef] = useState<{
    bucket: string;
    key: string;
  } | null>(null);

  const [model, setModel] = useState<string>(DEFAULT_MODEL);
  const [language, setLanguage] = useState<string>("auto");
  const [speakers, setSpeakers] = useState<string>("auto");
  const [llmCleanup, setLlmCleanup] = useState(false);
  const [cost, setCost] = useState<number | undefined>(undefined);

  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [pipelineStatus, setPipelineStatus] =
    useState<PipelineStatusItem | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [estimatedFinishAt, setEstimatedFinishAt] = useState<string | null>(null);
  const [workersMissing, setWorkersMissing] = useState(false);
  const [outOfTokensDialogOpen, setOutOfTokensDialogOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const pollIntervalRef = useRef<number | null>(null);
  const pollTimeoutRef = useRef<number | null>(null);
  const isMountedRef = useRef(true);
  const costTokenRef = useRef(0);

  const clearPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      clearPolling();
    };
  }, [clearPolling]);

  // Cost depends on the model and the cleanup flag, so resolve it server-side
  // rather than mirroring the multiplier table here. A token ref drops stale
  // responses when the user flips options quickly.
  useEffect(() => {
    const token = ++costTokenRef.current;
    pipelinesApi
      .previewCost({
        pipeline_name: "transcriber",
        input: { model, llm_cleanup: llmCleanup },
      })
      .then((res) => {
        if (costTokenRef.current === token) setCost(res.cost);
      })
      .catch(() => {
        if (costTokenRef.current === token) setCost(undefined);
      });
  }, [model, llmCleanup]);

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

  // Upload the picked recording and stash its S3 ref; a new file invalidates
  // the prior key.
  useEffect(() => {
    if (!audio || uploadedRef) return;
    let alive = true;
    setIsUploading(true);
    setErrorMessage(null);

    (async () => {
      try {
        const id = uuidv4();
        const ext = getFileExtension(audio.name);
        const result = await uploadMediaToS3(
          audio,
          "media",
          `user/${id}.${ext}`,
          (p) => {
            if (alive) setUploadProgress(p);
          },
        );
        if (alive) setUploadedRef({ bucket: result.bucket, key: result.key });
      } catch (err) {
        if (alive) {
          const message = err instanceof Error ? err.message : String(err);
          toast.error(`Upload failed: ${message}`);
          setAudio(null);
          setMediaKind(null);
        }
      } finally {
        if (alive) {
          setIsUploading(false);
          setUploadProgress(null);
        }
      }
    })();

    return () => {
      alive = false;
    };
  }, [audio, uploadedRef]);

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
    [clearPolling, refreshBalance],
  );

  const handleTranscribe = useCallback(async () => {
    if (!uploadedRef) return;

    if (!user) {
      navigate(
        `/auth?redirect=${encodeURIComponent(location.pathname + location.search)}`,
      );
      return;
    }

    if (cost !== undefined && balance !== null && balance < cost) {
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
        name: "transcriber_run_started",
        params: {
          pipeline_id: newPipelineId,
          model,
          llm_cleanup: llmCleanup,
          source_kind: mediaKind ?? "audio",
        },
      });

      try {
        await pipelinesApi.queuePipelines({
          trace_id: traceId,
          jobs: [
            {
              pipeline_id: newPipelineId,
              pipeline_name: "transcriber",
              input: {
                audio_bucket: uploadedRef.bucket,
                audio_key: uploadedRef.key,
                model,
                // "auto" is the UI's word for "let the model decide"; the
                // pipeline expects the field to simply be absent.
                ...(language === "auto" ? {} : { language }),
                ...(speakers === "auto"
                  ? {}
                  : { num_speakers: Number(speakers) }),
                llm_cleanup: llmCleanup,
                // Lets dispatch route a video through the extraction step
                // without having to guess from the file extension.
                ...(mediaKind ? { source_kind: mediaKind } : {}),
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
          "Transcription timed out. The serverless GPU may be cold-starting; please try again.",
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
    cost,
    balance,
    navigate,
    location.pathname,
    location.search,
    track,
    model,
    language,
    speakers,
    llmCleanup,
    mediaKind,
    refreshBalance,
    pollOnce,
    clearPolling,
  ]);

  const handleReset = useCallback(() => {
    setAudio(null);
    setMediaKind(null);
    setUploadProgress(null);
    setUploadedRef(null);
    setPipelineId(null);
    setPipelineStatus(null);
    setErrorMessage(null);
    setIsProcessing(false);
    setEstimatedFinishAt(null);
    setWorkersMissing(false);
    setCopied(false);
    clearPolling();
  }, [clearPolling]);

  const result =
    pipelineStatus?.status === "COMPLETED"
      ? (pipelineStatus.result as TranscriberResult | undefined)
      : null;
  const failed = pipelineStatus?.status === "FAILED";

  const {
    segments,
    isLoading: transcriptLoading,
    isError: transcriptError,
  } = useTranscript(result?.result_url, result?.preview ?? []);

  const handleCopy = useCallback(async () => {
    const text = segments
      .map((seg) => `${seg.speaker}: ${seg.text}`)
      .join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy to clipboard");
    }
  }, [segments]);

  const optionsDisabled = isProcessing || !!result;

  return (
    <main className="container mx-auto px-6 py-16 space-y-12 min-h-[calc(100vh-8rem)]">
      <DemoHeader
        title="Transcriber"
        cost={cost}
        description={
          <>
            Upload a recording — audio or video — and get it back as a
            transcript split by speaker: who said what, and when. Video is
            stripped to its audio track on a CPU container first, so the GPU
            never touches the frames. Silero VAD trims the silence,
            Whisper transcribes each speech chunk with word-level timestamps,
            and{" "}
            <a
              href="https://github.com/pyannote/pyannote-audio"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              pyannote <Github className="h-3.5 w-3.5" />
            </a>{" "}
            assigns a speaker to every word. Runs on a serverless GPU; ported
            from{" "}
            <a
              href="https://github.com/art-vozniuk/transcriber"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              transcriber <Github className="h-3.5 w-3.5" />
            </a>
            , an Apple-Silicon tool.
          </>
        }
        tagline={
          !audio && !result && !failed
            ? `Drop audio or video — up to ${MAX_MEDIA_MINUTES} minutes`
            : undefined
        }
      />

      <section className="max-w-3xl mx-auto space-y-6">
        {!result && !failed && (
          <>
            <AudioDropzone
              onFileSelect={(file, kind) => {
                setAudio(file);
                setMediaKind(kind);
              }}
              selectedFile={audio}
              disabled={isProcessing}
              progress={uploadProgress}
            />

            {audio && (
              <div className="space-y-5 rounded-xl border border-border bg-card p-5">
                <div className="grid gap-4 sm:grid-cols-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="model" className="text-xs">
                      Model
                    </Label>
                    <Select
                      value={model}
                      onValueChange={setModel}
                      disabled={optionsDisabled}
                    >
                      <SelectTrigger id="model">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {MODELS.map((m) => (
                          <SelectItem key={m.value} value={m.value}>
                            {m.label} · {m.multiplier}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="language" className="text-xs">
                      Language
                    </Label>
                    <Select
                      value={language}
                      onValueChange={setLanguage}
                      disabled={optionsDisabled}
                    >
                      <SelectTrigger id="language">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {LANGUAGES.map((l) => (
                          <SelectItem key={l.value} value={l.value}>
                            {l.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="speakers" className="text-xs">
                      Speakers
                    </Label>
                    <Select
                      value={speakers}
                      onValueChange={setSpeakers}
                      disabled={optionsDisabled}
                    >
                      <SelectTrigger id="speakers">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {SPEAKER_CHOICES.map((s) => (
                          <SelectItem key={s} value={s}>
                            {s === "auto" ? "Auto-detect" : s}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="flex items-start justify-between gap-4 border-t border-border pt-4">
                  <div className="space-y-0.5">
                    <Label htmlFor="llm-cleanup" className="text-sm">
                      LLM cleanup · ×2.5
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      A local Qwen2.5 pass that fixes punctuation, casing and
                      names. Much slower — capped at 15 minutes of audio.
                    </p>
                  </div>
                  <Switch
                    id="llm-cleanup"
                    checked={llmCleanup}
                    onCheckedChange={setLlmCleanup}
                    disabled={optionsDisabled}
                  />
                </div>

                <div className="flex flex-wrap items-center justify-center gap-3 border-t border-border pt-4">
                  <Button
                    onClick={handleTranscribe}
                    disabled={!uploadedRef || isUploading || isProcessing}
                  >
                    {isUploading ? (
                      "Uploading…"
                    ) : isProcessing ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        {pipelineStatus?.status === "RUNNING"
                          ? "Running on GPU…"
                          : "Queued…"}
                      </>
                    ) : !user ? (
                      "Sign in to transcribe"
                    ) : (
                      "Transcribe"
                    )}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={handleReset}
                    disabled={isProcessing}
                  >
                    Reset
                  </Button>
                </div>

                {isProcessing && (
                  <p className="text-center text-xs text-muted-foreground">
                    {workersMissing
                      ? "No workers available for this pipeline"
                      : remainingSeconds !== null
                        ? `~${formatRemaining(remainingSeconds)} left`
                        : "Warming up the GPU…"}
                  </p>
                )}
              </div>
            )}
          </>
        )}

        {errorMessage && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            {errorMessage}
          </div>
        )}

        {failed && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            Transcription failed: {pipelineStatus?.message ?? "unknown error"}
            <div className="mt-3">
              <Button variant="outline" size="sm" onClick={handleReset}>
                Try another recording
              </Button>
            </div>
          </div>
        )}

        {result && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>{result.segment_count} segments</span>
              <span>•</span>
              <span>
                {result.speakers.length}{" "}
                {result.speakers.length === 1 ? "speaker" : "speakers"}
              </span>
              {formatDuration(result.duration_s) && (
                <>
                  <span>•</span>
                  <span className="tabular-nums">
                    {formatDuration(result.duration_s)}
                  </span>
                </>
              )}
              {result.language && (
                <>
                  <span>•</span>
                  <span className="uppercase">{result.language}</span>
                </>
              )}
              {result.model && (
                <>
                  <span>•</span>
                  <span>{result.model}</span>
                </>
              )}
              {result.llm_cleanup && (
                <>
                  <span>•</span>
                  <span>LLM cleanup</span>
                </>
              )}
            </div>

            <div className="rounded-xl border border-border bg-card p-4 sm:p-6">
              <TranscriptView
                segments={segments}
                footer={
                  transcriptLoading ? (
                    <p className="flex items-center gap-2 pt-2 text-xs text-muted-foreground">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      Loading the full transcript…
                    </p>
                  ) : transcriptError ? (
                    <p className="pt-2 text-xs text-muted-foreground">
                      Showing the first {segments.length} segments — the full
                      transcript could not be loaded.{" "}
                      <a
                        href={result.result_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline"
                      >
                        Open the JSON
                      </a>
                      .
                    </p>
                  ) : null
                }
              />
            </div>

            <div className="flex flex-wrap items-center justify-center gap-3 text-xs text-muted-foreground">
              <Button
                size="sm"
                variant="outline"
                onClick={handleCopy}
                className="h-7"
              >
                {copied ? (
                  <Check className="mr-1.5 h-3.5 w-3.5" />
                ) : (
                  <Copy className="mr-1.5 h-3.5 w-3.5" />
                )}
                {copied ? "Copied" : "Copy text"}
              </Button>
              {result.txt_url && (
                <>
                  <span>•</span>
                  <a
                    href={result.txt_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                  >
                    Download .txt
                  </a>
                </>
              )}
              {result.srt_url && (
                <>
                  <span>•</span>
                  <a
                    href={result.srt_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                  >
                    Download .srt
                  </a>
                </>
              )}
              <span>•</span>
              <a
                href={result.result_url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:underline"
              >
                .json
              </a>
              <span>•</span>
              <Button
                size="sm"
                variant="outline"
                onClick={handleReset}
                className="h-7"
              >
                Try another recording
              </Button>
              {pipelineId && (
                <>
                  <span>•</span>
                  <SharePipelineButton
                    pipelineId={pipelineId}
                    pipelineDisplayName="Transcriber"
                    variant="compact"
                  />
                </>
              )}
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

export default Transcriber;
