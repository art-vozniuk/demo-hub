import { useEffect, useRef, useState } from "react";
import type { DetectedFace } from "@/api";
import { cn } from "@/lib/utils";

interface FaceSelectionOverlayProps {
  imageUrl: string;
  faces: DetectedFace[];
  // Native pixel dimensions of `faces` bboxes; used to scale them onto the rendered image.
  imageWidth: number;
  imageHeight: number;
  selectedFaceId: string | null;
  onFaceSelect: (faceId: string) => void;
  isAnalyzing?: boolean;
  errorMessage?: string | null;
}

const FaceSelectionOverlay = ({
  imageUrl,
  faces,
  imageWidth,
  imageHeight,
  selectedFaceId,
  onFaceSelect,
  isAnalyzing = false,
  errorMessage = null,
}: FaceSelectionOverlayProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [renderedSize, setRenderedSize] = useState<{ w: number; h: number } | null>(
    null
  );

  // Track the rendered image box so bbox overlays follow responsive resizes.
  useEffect(() => {
    if (!containerRef.current) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setRenderedSize({
          w: entry.contentRect.width,
          h: entry.contentRect.height,
        });
      }
    });

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const scaleX =
    renderedSize && imageWidth > 0 ? renderedSize.w / imageWidth : 1;
  const scaleY =
    renderedSize && imageHeight > 0 ? renderedSize.h / imageHeight : 1;

  return (
    <div className="relative max-w-md mx-auto">
      <div
        ref={containerRef}
        className="relative rounded-xl overflow-hidden shadow-2xl border border-border"
      >
        <img
          src={imageUrl}
          alt="Uploaded"
          className="w-full h-auto block"
        />

        {renderedSize &&
          !isAnalyzing &&
          faces.map((face) => {
            const [x1, y1, x2, y2] = face.bbox;
            const left = x1 * scaleX;
            const top = y1 * scaleY;
            const width = (x2 - x1) * scaleX;
            const height = (y2 - y1) * scaleY;
            const isSelected = face.id === selectedFaceId;

            return (
              <button
                type="button"
                key={face.id}
                onClick={() => onFaceSelect(face.id)}
                aria-pressed={isSelected}
                aria-label={`Select face ${face.id}`}
                className={cn(
                  "absolute rounded-md transition-all duration-200",
                  "border-2 cursor-pointer",
                  isSelected
                    ? "border-primary shadow-[0_0_0_2px_rgba(255,255,255,0.4),_0_0_24px_rgba(99,102,241,0.7)] bg-primary/10"
                    : "border-white/70 hover:border-primary/80 hover:bg-primary/5"
                )}
                style={{ left, top, width, height }}
              />
            );
          })}

        {isAnalyzing && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/70 backdrop-blur-sm">
            <div className="text-center">
              <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-primary border-r-transparent mb-2" />
              <p className="text-sm font-medium">Detecting faces…</p>
            </div>
          </div>
        )}

        {!isAnalyzing && errorMessage && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/80 backdrop-blur-sm">
            <p className="text-destructive text-sm font-medium px-4 text-center">
              {errorMessage}
            </p>
          </div>
        )}
      </div>

      {!isAnalyzing && !errorMessage && faces.length > 1 && (
        <p className="text-xs text-muted-foreground mt-2 text-center">
          {faces.length} faces detected — tap to choose which one to swap.
        </p>
      )}
      {!isAnalyzing && !errorMessage && faces.length === 1 && (
        <p className="text-xs text-muted-foreground mt-2 text-center">
          Face detected.
        </p>
      )}
    </div>
  );
};

export default FaceSelectionOverlay;
