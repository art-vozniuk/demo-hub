import { useMemo } from "react";

import type { TranscriptSegment } from "@/api";
import { cn } from "@/lib/utils";

// Speakers are anonymous (SPEAKER_00, SPEAKER_01, ...), so colour is the only
// thing that makes a turn scannable. Assigned by order of first appearance so
// the same recording always looks the same.
const SPEAKER_STYLES = [
  "text-cyan-400 border-cyan-400/40",
  "text-violet-400 border-violet-400/40",
  "text-amber-400 border-amber-400/40",
  "text-emerald-400 border-emerald-400/40",
  "text-rose-400 border-rose-400/40",
  "text-sky-400 border-sky-400/40",
  "text-lime-400 border-lime-400/40",
  "text-fuchsia-400 border-fuchsia-400/40",
];

const formatTimestamp = (seconds: number): string => {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};

const speakerLabel = (speaker: string): string =>
  speaker.replace(/^SPEAKER[_-]?/i, "Speaker ");

interface Props {
  segments: TranscriptSegment[];
  className?: string;
  /** Rendered under the last segment — "loading the rest", a download link… */
  footer?: React.ReactNode;
}

export const TranscriptView = ({ segments, className, footer }: Props) => {
  const styleBySpeaker = useMemo(() => {
    const map = new Map<string, string>();
    for (const seg of segments) {
      if (!map.has(seg.speaker)) {
        map.set(seg.speaker, SPEAKER_STYLES[map.size % SPEAKER_STYLES.length]);
      }
    }
    return map;
  }, [segments]);

  if (segments.length === 0) {
    return (
      <p className={cn("text-sm text-muted-foreground", className)}>
        No speech was detected in this recording.
      </p>
    );
  }

  return (
    <div className={cn("space-y-4", className)}>
      {segments.map((seg, i) => {
        const style = styleBySpeaker.get(seg.speaker) ?? SPEAKER_STYLES[0];
        return (
          <div
            key={`${seg.start}-${i}`}
            className={cn("border-l-2 pl-3 sm:pl-4", style)}
          >
            <div className="flex items-baseline gap-2 text-xs">
              <span className={cn("font-semibold", style)}>
                {speakerLabel(seg.speaker)}
              </span>
              <span className="text-muted-foreground tabular-nums">
                {formatTimestamp(seg.start)} – {formatTimestamp(seg.end)}
              </span>
            </div>
            <p className="mt-1 text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap">
              {seg.text}
            </p>
          </div>
        );
      })}
      {footer}
    </div>
  );
};

export default TranscriptView;
