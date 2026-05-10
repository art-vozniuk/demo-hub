import { Coins } from "lucide-react";

import { cn } from "@/lib/utils";

interface CostBadgeProps {
  cost: number;
  size?: "sm" | "md";
  className?: string;
}

const CostBadge = ({ cost, size = "sm", className }: CostBadgeProps) => {
  const isCompact = size === "sm";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-300",
        isCompact ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm",
        className,
      )}
      title={`Costs ${cost} ${cost === 1 ? "token" : "tokens"} per generation`}
    >
      <Coins className={isCompact ? "h-3 w-3" : "h-4 w-4"} />
      {cost}
    </span>
  );
};

export default CostBadge;
