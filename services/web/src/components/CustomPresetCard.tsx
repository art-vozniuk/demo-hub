import { ArrowRight, ImagePlus, Sparkles } from "lucide-react";

interface CustomPresetCardProps {
  onSelect: () => void;
}

const CustomPresetCard = ({ onSelect }: CustomPresetCardProps) => {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="group text-left rounded-lg overflow-hidden border-2 border-dashed border-primary/40 bg-gradient-to-br from-primary/15 via-primary/5 to-transparent hover:border-primary hover:bg-primary/10 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
    >
      <div className="aspect-square w-full overflow-hidden bg-transparent flex items-center justify-center">
        <div className="flex flex-col items-center gap-3 p-6 text-center">
          <div className="rounded-full bg-primary/20 p-4 ring-1 ring-primary/40 group-hover:ring-primary group-hover:bg-primary/30 transition-all">
            <ImagePlus className="h-6 w-6 text-primary" />
          </div>
          <p className="text-base font-semibold flex items-center justify-center gap-1.5">
            Your own prompt
            <Sparkles className="h-4 w-4 text-primary animate-pulse" />
          </p>
        </div>
      </div>
      <div className="p-4 space-y-1.5">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold tracking-tight">Custom</h3>
          <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
        </div>
        <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed">
          Skip the presets — drop in any photo, write your own prompt, pick a quality tier.
        </p>
      </div>
    </button>
  );
};

export default CustomPresetCard;
