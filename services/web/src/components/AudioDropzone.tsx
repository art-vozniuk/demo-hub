import { useCallback, useState } from "react";
import { AudioLines, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

// Mirrors the ceilings in services/modal/transcriber/app.py. Checked here so
// the user finds out before a multi-megabyte upload, not after.
export const MAX_AUDIO_MB = 100;
export const MAX_AUDIO_MINUTES = 30;

// Browsers are inconsistent about audio MIME types (m4a shows up as
// audio/x-m4a, audio/mp4 or nothing at all), so accept anything that either
// declares an audio type or carries a known extension.
const ACCEPTED_EXTENSIONS = [
  "mp3", "m4a", "mp4", "wav", "flac", "ogg", "oga", "opus", "webm", "aac", "wma",
];

const ACCEPT_ATTR = [
  "audio/*",
  ...ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`),
].join(",");

const extensionOf = (name: string): string =>
  name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";

const formatDuration = (seconds: number): string => {
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
};

/** Read duration from the browser's decoder. Resolves null when it can't
 *  decode the container — the server re-checks with ffprobe either way. */
const probeDuration = (file: File): Promise<number | null> =>
  new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const audio = new Audio();
    const done = (value: number | null) => {
      URL.revokeObjectURL(url);
      resolve(value);
    };
    audio.preload = "metadata";
    audio.onloadedmetadata = () =>
      done(Number.isFinite(audio.duration) ? audio.duration : null);
    audio.onerror = () => done(null);
    audio.src = url;
  });

interface AudioDropzoneProps {
  onFileSelect: (file: File | null) => void;
  selectedFile: File | null;
  disabled?: boolean;
}

const AudioDropzone = ({
  onFileSelect,
  selectedFile,
  disabled = false,
}: AudioDropzoneProps) => {
  const [isDragging, setIsDragging] = useState(false);
  const [duration, setDuration] = useState<number | null>(null);

  const accept = useCallback(
    async (file: File) => {
      const looksLikeAudio =
        file.type.startsWith("audio/") ||
        ACCEPTED_EXTENSIONS.includes(extensionOf(file.name));
      if (!looksLikeAudio) {
        toast.error(
          `Unsupported file. Try ${ACCEPTED_EXTENSIONS.slice(0, 5).join(", ")}…`,
        );
        return;
      }
      if (file.size > MAX_AUDIO_MB * 1024 * 1024) {
        toast.error(`File must be under ${MAX_AUDIO_MB} MB`);
        return;
      }

      const seconds = await probeDuration(file);
      if (seconds !== null && seconds > MAX_AUDIO_MINUTES * 60) {
        toast.error(
          `Recording is ${Math.round(seconds / 60)} min; the limit is ` +
            `${MAX_AUDIO_MINUTES} min`,
        );
        return;
      }

      setDuration(seconds);
      onFileSelect(file);
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
    onFileSelect(null);
  };

  if (selectedFile) {
    return (
      <div className="w-full max-w-2xl mx-auto">
        <div className="card-gradient relative overflow-hidden rounded-xl border border-border p-6">
          <div className="flex items-center gap-4">
            <div className="rounded-lg bg-primary/10 p-3">
              <AudioLines className="h-6 w-6 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="truncate font-medium">{selectedFile.name}</p>
              <p className="text-sm text-muted-foreground tabular-nums">
                {(selectedFile.size / 1024 / 1024).toFixed(1)} MB
                {duration !== null && ` · ${formatDuration(duration)}`}
              </p>
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
          accept={ACCEPT_ATTR}
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
              MP3, M4A, WAV, FLAC, OGG, WEBM · up to {MAX_AUDIO_MINUTES} min ·
              max {MAX_AUDIO_MB} MB
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AudioDropzone;
