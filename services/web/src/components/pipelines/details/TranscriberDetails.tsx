import { AudioLines } from "lucide-react";

import type { TranscriberResult, UserPipelineItem } from "@/api";
import { getPublicImageUrl } from "@/lib/s3";
import TranscriptView from "@/components/transcriber/TranscriptView";
import { useTranscript } from "@/components/transcriber/useTranscript";

interface Props {
  pipeline: UserPipelineItem;
}

// Long transcripts would swamp the gallery card, so the list view shows a
// bounded excerpt with a link to the full artifacts.
const EXCERPT_SEGMENTS = 6;

const formatDuration = (seconds: unknown): string | null => {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return null;
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, "0")}s`;
};

const TranscriberDetails = ({ pipeline }: Props) => {
  const input = pipeline.input ?? {};
  const result = (pipeline.result ?? {}) as Partial<TranscriberResult>;
  const sourceUrl = getPublicImageUrl(
    typeof input.audio_bucket === "string" ? input.audio_bucket : null,
    typeof input.audio_key === "string" ? input.audio_key : null,
  );

  const { segments } = useTranscript(result.result_url, result.preview ?? []);
  const excerpt = segments.slice(0, EXCERPT_SEGMENTS);
  const duration = formatDuration(result.duration_s);
  // For a video run the source key is the video, which an <audio> element
  // can't play — prefer the extracted track the pipeline produced.
  const playableUrl = result.extracted_audio_url || sourceUrl;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <AudioLines className="h-3.5 w-3.5" />
          {duration ?? "audio"}
        </span>
        {typeof result.segment_count === "number" && (
          <>
            <span>•</span>
            <span>{result.segment_count} segments</span>
          </>
        )}
        {result.speakers && result.speakers.length > 0 && (
          <>
            <span>•</span>
            <span>
              {result.speakers.length}{" "}
              {result.speakers.length === 1 ? "speaker" : "speakers"}
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
      </div>

      {playableUrl && (
        <audio
          controls
          preload="none"
          src={playableUrl}
          className="w-full max-w-md"
        >
          <a href={playableUrl}>Download the audio</a>
        </audio>
      )}

      {excerpt.length > 0 && <TranscriptView segments={excerpt} />}

      {(result.result_url || result.txt_url || result.srt_url) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {segments.length > excerpt.length && (
            <span>
              +{segments.length - excerpt.length} more segments in the download
            </span>
          )}
          {result.txt_url && (
            <a
              href={result.txt_url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
            >
              .txt
            </a>
          )}
          {result.srt_url && (
            <a
              href={result.srt_url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
            >
              .srt
            </a>
          )}
          {result.result_url && (
            <a
              href={result.result_url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
            >
              .json
            </a>
          )}
        </div>
      )}
    </div>
  );
};

export default TranscriberDetails;
