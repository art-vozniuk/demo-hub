import { Check } from "lucide-react";
import type { RecastTemplateRead } from "@/api";
import { cn } from "@/lib/utils";

interface TemplateCardProps {
  template: RecastTemplateRead;
  isSelected: boolean;
  isDisabled: boolean;
  onToggle: (template: RecastTemplateRead) => void;
}

const TemplateCard = ({
  template,
  isSelected,
  isDisabled,
  onToggle,
}: TemplateCardProps) => {
  const handleClick = () => {
    if (!isDisabled || isSelected) {
      onToggle(template);
    }
  };

  return (
    <div
      onClick={handleClick}
      className={cn(
        "group relative overflow-hidden rounded-lg cursor-pointer transition-all duration-300",
        "hover:shadow-xl hover:scale-[1.02]",
        isDisabled && !isSelected && "opacity-40 cursor-not-allowed hover:scale-100",
        isSelected && "ring-4 ring-primary shadow-2xl"
      )}
    >
      <div className="relative">
        <img
          src={template.url}
          alt={template.name || "Template"}
          className="w-full h-auto object-cover"
          loading="lazy"
        />
        
        {isSelected && (
          <div className="absolute inset-0 bg-primary/20 flex items-center justify-center animate-fade-in">
            <div className="bg-primary rounded-full p-3 shadow-lg">
              <Check className="h-8 w-8 text-primary-foreground" strokeWidth={3} />
            </div>
          </div>
        )}

        {isDisabled && !isSelected && (
          <div className="absolute inset-0 bg-black/40" />
        )}
      </div>

      {template.name && (
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 via-black/50 to-transparent p-3">
          <p className="text-white text-sm font-medium truncate">
            {template.name}
          </p>
        </div>
      )}
    </div>
  );
};

export default TemplateCard;

