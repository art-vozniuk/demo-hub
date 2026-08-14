import { useCallback, useState } from "react";
import { AudioLines, Film, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { toast } from "sonner";
import {
  AUDIO_EXTENSIONS,
  MAX_MEDIA_MB,
  MAX_MEDIA_MINUTES,
  MEDIA_ACCEPT_ATTR,
  formatMediaDuration,
  formatMediaSize,
  mediaKindOf,
  probeMediaDuration,
  type MediaKind,
} from "@/lib/media";
import type { UploadProgress } from "@/lib/s3";

interface AudioDropzoneProps {
  onFileSelect: (file: File | null, kind: MediaKind | null) => void;
  selectedFile: File | null;
  disabled?: boolean;
  /** Set while the file is uploading, to show real progress. */
  progress?: UploadProgress | null;
}

const AudioDropzone = ({
  onFileSelect,
  selectedFile,
  disabled = false,
  progress = null,
}: AudioDropzoneProps) => {
  const [isDragging, setIsDragging] = useState(false);
  const [duration, setDuration] = useState<number | null>(null);
  const [kind, setKind] = useState<MediaKind | null>(null);

  const accept = useCallback(
    async (file: File) => {
      const mediaKind = mediaKindOf(file);
      if (!mediaKind) {
        toast.error(
          `Unsupported file. Upload audio (${AUDIO_EXTENSIONS.slice(0, 4).join(
            ", ",
          )}…) or video (mov, mp4, mkv…).`,
        );
        return;
      }
      if (file.size > MAX_MEDIA_MB * 1024 * 1024) {
        toast.error(
          `File must be under ${(MAX_MEDIA_MB / 1024).toFixed(0)} GB — this ` +
            `one is ${formatMediaSize(file.size)}`,
        );
        return;
      }

      const seconds = await probeMediaDuration(file, mediaKind);
      if (seconds !== null && seconds > MAX_MEDIA_MINUTES * 60) {
        toast.error(
          `Recording is ${Math.round(seconds / 60)} min; the limit is ` +
            `${MAX_MEDIA_MINUTES} min`,
        );
        return;
      }

      setDuration(seconds);
      setKind(mediaKind);
      onFileSelect(file, mediaKind);
    },
    [onFileSelect],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragging(false);
      if (disabled) return;
      const file = e.dataTransfer.files[0];
      if (file) void accept(file);
    },
    [accept, disabled],
  );

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void accept(file);
    // Let the same file be picked again after a reset.
    e.target.value = "";
  };

  const handleRemove = () => {
    setDuration(null);
    setKind(null);
    onFileSelect(null, null);
  };

  if (selectedFile) {
    const percent =
      progress && progress.total > 0
        ? Math.min(100, Math.round((progress.loaded / progress.total) * 100))
        : null;
    const Icon = kind === "video" ? Film : AudioLines;

    return (
      <div className="w-full max-w-2xl mx-auto">
        <div className="card-gradient relative overflow-hidden rounded-xl border border-border p-6">
          <div className="flex items-center gap-4">
            <div className="rounded-lg bg-primary/10 p-3">
              <Icon className="h-6 w-6 text-primary" />
            </div>
            <div className="flex-1 min-w-0 space-y-1">
              <p className="truncate font-medium">{selectedFile.name}</p>
              <p className="text-sm text-muted-foreground tabular-nums">
                {formatMediaSize(selectedFile.size)}
                {duration !== null && ` · ${formatMediaDuration(duration)}`}
                {kind === "video" && " · video"}
              </p>
              {percent !== null && progress && (
                <div className="space-y-1 pt-1">
                  <Progress value={percent} className="h-1.5" />
                  <p className="text-xs text-muted-foreground tabular-nums">
                    Uploading {percent}% ({formatMediaSize(progress.loaded)} of{" "}
                    {formatMediaSize(progress.total)})
                  </p>
                </div>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleRemove}
              disabled={disabled}
              className="hover:bg-destructive/10 hover:text-destructive"
              aria-label="Remove file"
            >
              <X className="h-5 w-5" />
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div
        onDrop={handleDrop}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        className={`relative overflow-hidden rounded-xl border-2 border-dashed p-12 transition-all ${
          isDragging
            ? "border-primary bg-primary/5"
            : "border-border bg-card hover:border-primary/50"
        } ${disabled ? "opacity-60" : ""}`}
      >
        <input
          type="file"
          id="audio-upload"
          className="absolute inset-0 cursor-pointer opacity-0"
          accept={MEDIA_ACCEPT_ATTR}
          disabled={disabled}
          onChange={handleFileInput}
        />
        <div className="flex flex-col items-center gap-4 text-center">
          <div className="rounded-full bg-primary/10 p-4">
            <Upload className="h-8 w-8 text-primary" />
          </div>
          <div>
            <p className="text-lg font-medium">
              Drop a recording here, or{" "}
              <label
                htmlFor="audio-upload"
                className="cursor-pointer text-primary underline-offset-4 hover:underline"
              >
                browse
              </label>
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Audio (MP3, M4A, WAV, FLAC…) or video (MOV, MP4, MKV…) · up to{" "}
              {MAX_MEDIA_MINUTES} min
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Video is stripped to its audio track on the way in, so only the
              sound is transcribed.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AudioDropzone;
