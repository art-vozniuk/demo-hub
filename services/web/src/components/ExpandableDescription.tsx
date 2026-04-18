import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

type ExpandableDescriptionProps = {
  /** Full description content; first line is always visible, rest reveals on click. */
  children: ReactNode;
  /** Text-block styling hook — defaults match the hero copy on demo pages. */
  className?: string;
};

/**
 * Shows the first line of a description with a chevron; click anywhere on
 * the block to expand and reveal the full content. Hitting "show less"
 * collapses it back to one line. Used on demo pages so the hero copy
 * doesn't eat half the viewport before the demo itself.
 */
export const ExpandableDescription = ({
  children,
  className = "text-xl text-muted-foreground max-w-2xl mx-auto",
}: ExpandableDescriptionProps) => {
  const [open, setOpen] = useState(false);

  return (
    <div className={className}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="group text-left w-full cursor-pointer"
      >
        {/* line-clamp-1 sets display: -webkit-box and clips to a single line.
         *  Don't add `block` alongside it — `block` wins the display cascade
         *  and disables clamping. When expanded we switch to a plain block. */}
        <span className={open ? "block" : "line-clamp-1"}>
          {children}
        </span>
        <span className="mt-1 inline-flex items-center gap-1 text-sm text-muted-foreground/60 group-hover:text-foreground/80 transition-colors">
          <span className="opacity-70">{open ? "Show less" : "Show more"}</span>
          <ChevronDown
            className={`h-3.5 w-3.5 transition-transform duration-200 ${
              open ? "rotate-180" : ""
            }`}
            aria-hidden
          />
        </span>
      </button>
    </div>
  );
};
