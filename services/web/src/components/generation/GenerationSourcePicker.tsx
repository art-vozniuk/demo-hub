// Source-selection step shared by the editor's GenerateAssetOverlay and the
// standalone Trellis demo page. Fully controlled: the parent owns
// sourceMode/prompt/imageFile; this component owns only the transient preview
// URL and drag state. Renders the Text/Image toggle, the matching input, and
// the primary action button.

import { ReactNode, useEffect, useRef, useState } from "react";
import { ImagePlus, Loader2, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export type SourceMode = "text" | "image";

const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const ACCEPTED_IMAGE_TYPES = "image/png,image/jpeg,image/webp";
const MB = 1024 * 1024;

interface Props {
  sourceMode: SourceMode;
  onSourceModeChange: (mode: SourceMode) => void;
  prompt: string;
  onPromptChange: (value: string) => void;
  imageFile: File | null;
  onImageFileChange: (file: File | null) => void;
  onSubmit: () => void;
  canSubmit: boolean;
  submitting: boolean;
  promptPlaceholder?: string;
  textSubmitLabel?: string;
  imageSubmitLabel?: string;
  // Optional small note (e.g. a cost line) rendered above the action button.
  costNote?: ReactNode;
}

export const GenerationSourcePicker = ({
  sourceMode,
  onSourceModeChange,
  prompt,
  onPromptChange,
  imageFile,
  onImageFileChange,
  onSubmit,
  canSubmit,
  submitting,
  promptPlaceholder = "e.g. a small wooden toy train",
  textSubmitLabel = "Generate",
  imageSubmitLabel = "Continue",
  costNote,
}: Props) => {
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Object URL for the upload preview; revoke on swap/unmount.
  useEffect(() => {
    if (!imageFile) {
      setImagePreview(null);
      return;
    }
    const url = URL.createObjectURL(imageFile);
    setImagePreview(url);
    return () => URL.revokeObjectURL(url);
  }, [imageFile]);

  const onPickFile = (file: File) => {
    if (!file.type.startsWith("image/")) {
      toast.error("Please choose an image file.");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      toast.error(`Image is too large (max ${MAX_IMAGE_BYTES / MB} MB).`);
      return;
    }
    onImageFileChange(file);
  };

  return (
    <div className="space-y-3">
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={sourceMode}
        onValueChange={(v) => v && onSourceModeChange(v as SourceMode)}
        className="justify-start"
      >
        <ToggleGroupItem value="text" className="text-[11px] px-3">
          Text
        </ToggleGroupItem>
        <ToggleGroupItem value="image" className="text-[11px] px-3">
          Image
        </ToggleGroupItem>
      </ToggleGroup>

      {sourceMode === "text" ? (
        <>
          <Label htmlFor="generate-prompt" className="text-xs">
            Prompt
          </Label>
          <Textarea
            id="generate-prompt"
            value={prompt}
            onChange={(e) => onPromptChange(e.target.value)}
            placeholder={promptPlaceholder}
            rows={3}
          />
        </>
      ) : (
        <>
          <Label className="text-xs">Image</Label>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_IMAGE_TYPES}
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onPickFile(f);
              e.target.value = "";
            }}
          />
          {imageFile && imagePreview ? (
            <div className="flex items-center gap-3 rounded-md border border-border/60 px-3 py-2">
              <img
                src={imagePreview}
                alt={imageFile.name}
                className="h-16 w-16 rounded object-cover bg-muted"
              />
              <div className="flex-1 min-w-0">
                <div className="text-xs truncate">{imageFile.name}</div>
                <div className="text-[10px] text-muted-foreground">
                  {(imageFile.size / 1024).toFixed(0)} KB
                </div>
              </div>
              <button
                type="button"
                onClick={() => onImageFileChange(null)}
                className="text-muted-foreground hover:text-destructive"
                aria-label="Remove image"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDragging(false);
                const f = e.dataTransfer.files?.[0];
                if (f) onPickFile(f);
              }}
              className={cn(
                "w-full rounded-md border border-dashed px-4 py-8 text-center cursor-pointer",
                "border-border/60 hover:border-border hover:bg-muted/30 transition-colors",
                isDragging && "border-primary/70 bg-primary/5",
              )}
            >
              <ImagePlus className="h-6 w-6 mx-auto mb-1.5 text-muted-foreground" />
              <div className="text-xs">Drop image or click to upload</div>
              <div className="text-[10px] text-muted-foreground">
                PNG, JPG, WebP · up to {MAX_IMAGE_BYTES / MB} MB
              </div>
            </button>
          )}
        </>
      )}

      {costNote && (
        <div className="text-[11px] text-muted-foreground tabular-nums">
          {costNote}
        </div>
      )}

      <div className="flex justify-end pt-1">
        <Button
          size="sm"
          onClick={onSubmit}
          disabled={!canSubmit}
          className="gap-1"
        >
          {submitting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {sourceMode === "text" ? textSubmitLabel : imageSubmitLabel}
        </Button>
      </div>
    </div>
  );
};

export default GenerationSourcePicker;
