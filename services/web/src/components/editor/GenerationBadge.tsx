/**
 * Compact viewport badge for a backgrounded generation session.
 *
 * Hidden when there is nothing to surface (idle or the overlay is
 * already open). Clicking re-opens the overlay so the user can review
 * the result, iterate, or cancel.
 */

import { Loader2, Sparkles, AlertCircle, ImageIcon } from "lucide-react";

import { useGenerationSession } from "@/contexts/GenerationSessionContext";

interface Props {
  // True when the overlay is open — we hide the badge so we don't
  // double up.
  hidden: boolean;
  onClick: () => void;
}

export const GenerationBadge = ({ hidden, onClick }: Props) => {
  const session = useGenerationSession();
  if (hidden) return null;
  if (session.phase === "idle") return null;

  const { Icon, label, spinning, tone } = (() => {
    switch (session.phase) {
      case "flux-pending":
        return {
          Icon: Loader2,
          label: session.iterating
            ? "Iterating on image…"
            : "Generating image…",
          spinning: true,
          tone: "primary" as const,
        };
      case "flux-ready":
        return {
          Icon: ImageIcon,
          label: "Image ready — review",
          spinning: false,
          tone: "primary" as const,
        };
      case "sharp-pending":
        return {
          Icon: Loader2,
          label: "Rendering splat…",
          spinning: true,
          tone: "primary" as const,
        };
      case "failed":
        return {
          Icon: AlertCircle,
          label: "Generation failed",
          spinning: false,
          tone: "destructive" as const,
        };
      default:
        return {
          Icon: Sparkles,
          label: "",
          spinning: false,
          tone: "primary" as const,
        };
    }
  })();

  return (
    <button
      type="button"
      onClick={onClick}
      className={
        // Top-left so we don't collide with the existing scene-load
        // pill on top-right.
        "absolute top-3 left-3 z-20 rounded-full border bg-background/85 backdrop-blur px-3 py-1 shadow-md " +
        "flex items-center gap-1.5 text-[11px] cursor-pointer hover:bg-background transition " +
        (tone === "destructive"
          ? "border-destructive/40 text-destructive"
          : "border-border text-foreground/90")
      }
    >
      <Icon
        className={"h-3 w-3 " + (spinning ? "animate-spin text-primary" : "")}
      />
      <span className="tabular-nums">{label}</span>
    </button>
  );
};
