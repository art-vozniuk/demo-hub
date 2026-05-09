import { ArrowRight } from "lucide-react";
import type { GenerativePresetRead } from "@/api";

interface PresetCardProps {
  preset: GenerativePresetRead;
  onSelect: (preset: GenerativePresetRead) => void;
}

const PresetCard = ({ preset, onSelect }: PresetCardProps) => {
  return (
    <button
      type="button"
      onClick={() => onSelect(preset)}
      className="group text-left rounded-lg overflow-hidden border border-border bg-muted/20 hover:bg-muted/40 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
    >
      <div className="aspect-[3/4] w-full overflow-hidden bg-black">
        <img
          src={preset.preview_image_url}
          alt={preset.title}
          loading="lazy"
          className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
        />
      </div>
      <div className="p-4 space-y-1.5">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold tracking-tight">{preset.title}</h3>
          <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
        </div>
        {preset.description && (
          <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed">
            {preset.description}
          </p>
        )}
      </div>
    </button>
  );
};

export default PresetCard;
