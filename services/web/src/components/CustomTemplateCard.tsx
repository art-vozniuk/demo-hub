import { ImagePlus, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

interface CustomTemplateCardProps {
  onSelect: () => void;
  isDisabled?: boolean;
}

const CustomTemplateCard = ({
  onSelect,
  isDisabled = false,
}: CustomTemplateCardProps) => {
  return (
    <div
      onClick={isDisabled ? undefined : onSelect}
      role="button"
      tabIndex={isDisabled ? -1 : 0}
      onKeyDown={(e) => {
        if (!isDisabled && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "group relative overflow-hidden rounded-lg cursor-pointer transition-all duration-300",
        "border-2 border-dashed border-primary/40 bg-gradient-to-br from-primary/15 via-primary/5 to-transparent",
        "hover:border-primary hover:shadow-2xl hover:scale-[1.02]",
        "aspect-[3/4] flex items-center justify-center",
        isDisabled && "opacity-40 cursor-not-allowed hover:scale-100 hover:border-primary/40"
      )}
    >
      <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity bg-gradient-to-br from-primary/20 via-transparent to-primary/10" />

      <div className="relative z-10 flex flex-col items-center gap-3 p-6 text-center">
        <div className="rounded-full bg-primary/20 p-4 ring-1 ring-primary/40 group-hover:ring-primary group-hover:bg-primary/30 transition-all">
          <ImagePlus className="h-6 w-6 text-primary" />
        </div>
        <div className="space-y-1">
          <p className="text-base font-semibold flex items-center justify-center gap-1.5">
            Your own template
            <Sparkles className="h-4 w-4 text-primary animate-pulse" />
          </p>
          <p className="text-xs text-muted-foreground max-w-[14rem]">
            Upload any photo as your template and swap a face into it.
          </p>
        </div>
      </div>
    </div>
  );
};

export default CustomTemplateCard;
