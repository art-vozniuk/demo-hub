import { useQuery } from "@tanstack/react-query";

import type { TranscriptSegment } from "@/api";

interface TranscriptDocument {
  meta?: Record<string, unknown>;
  segments?: TranscriptSegment[];
}

const isSegment = (value: unknown): value is TranscriptSegment => {
  const seg = value as TranscriptSegment | null;
  return (
    !!seg &&
    typeof seg.start === "number" &&
    typeof seg.end === "number" &&
    typeof seg.text === "string" &&
    typeof seg.speaker === "string"
  );
};

/**
 * Full transcript for a finished run.
 *
 * The pipeline result carries only the first segments inline (`preview`) so the
 * database row stays small; the whole thing lives in the JSON at `resultUrl`.
 * Those preview segments render immediately and are what we fall back to if the
 * fetch fails — a partial transcript plus a download link beats an empty page.
 */
export function useTranscript(
  resultUrl: string | null | undefined,
  preview: TranscriptSegment[],
): {
  segments: TranscriptSegment[];
  isLoading: boolean;
  isError: boolean;
} {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["transcript", resultUrl],
    enabled: !!resultUrl,
    staleTime: Infinity,
    retry: 1,
    queryFn: async (): Promise<TranscriptSegment[]> => {
      const response = await fetch(resultUrl!);
      if (!response.ok) {
        throw new Error(`transcript fetch failed: ${response.status}`);
      }
      const doc = (await response.json()) as TranscriptDocument;
      return (doc.segments ?? []).filter(isSegment);
    },
  });

  return {
    segments: data && data.length > 0 ? data : preview,
    isLoading,
    isError,
  };
}
