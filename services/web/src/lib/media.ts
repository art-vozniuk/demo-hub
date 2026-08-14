// What counts as an uploadable recording, and how to describe one. Kept out of
// the dropzone component so the page can share the limits without importing a
// component (and so fast-refresh stays happy).

// Mirrors MAX_AUDIO_SECONDS in services/modal/transcriber/app.py. Checked in
// the browser so the user finds out before uploading, not after.
export const MAX_MEDIA_MINUTES = 90;

// Video is the reason this is measured in gigabytes: 90 minutes at a phone's
// bitrate is well over one. The real ceiling is whatever the storage service
// allows — uploadMediaToS3 turns a rejection into a readable error.
export const MAX_MEDIA_MB = 2048;

export type MediaKind = "audio" | "video";

export const AUDIO_EXTENSIONS = [
  "mp3", "m4a", "wav", "flac", "ogg", "oga", "opus", "aac", "wma", "aiff", "amr",
];

// Kept in step with VIDEO_EXTENSIONS in services/common/constants.py — a
// mismatch only costs a needless extraction step, never a wrong result.
export const VIDEO_EXTENSIONS = [
  "mov", "mp4", "m4v", "mkv", "avi", "webm", "wmv", "flv", "mpg", "mpeg",
  "mts", "m2ts", "ts", "3gp", "ogv",
];

export const MEDIA_ACCEPT_ATTR = [
  "audio/*",
  "video/*",
  ...[...AUDIO_EXTENSIONS, ...VIDEO_EXTENSIONS].map((ext) => `.${ext}`),
].join(",");

const extensionOf = (name: string): string =>
  name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";

/**
 * Which kind the pipeline should treat this file as, or null if it isn't media.
 *
 * Browsers are inconsistent about MIME types — a .mov can arrive as
 * video/quicktime, an .m4a as audio/x-m4a, audio/mp4 or nothing at all — so the
 * declared type leads and the extension decides when it's blank.
 */
export const mediaKindOf = (file: File): MediaKind | null => {
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "audio";
  const ext = extensionOf(file.name);
  if (VIDEO_EXTENSIONS.includes(ext)) return "video";
  if (AUDIO_EXTENSIONS.includes(ext)) return "audio";
  return null;
};

export const formatMediaDuration = (seconds: number): string => {
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
};

export const formatMediaSize = (bytes: number): string => {
  const mb = bytes / 1024 / 1024;
  return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(1)} MB`;
};

/**
 * Duration from the browser's own decoder. Resolves null when it can't decode
 * the container — the server re-checks with ffprobe either way, so a null here
 * only means "we couldn't warn early".
 */
export const probeMediaDuration = (
  file: File,
  kind: MediaKind,
): Promise<number | null> =>
  new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const element = document.createElement(kind === "video" ? "video" : "audio");
    const done = (value: number | null) => {
      URL.revokeObjectURL(url);
      resolve(value);
    };
    element.preload = "metadata";
    element.onloadedmetadata = () =>
      done(Number.isFinite(element.duration) ? element.duration : null);
    element.onerror = () => done(null);
    element.src = url;
  });
