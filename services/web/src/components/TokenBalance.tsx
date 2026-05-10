import { Link } from "react-router-dom";
import { Coins } from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useWallet } from "@/contexts/WalletContext";
import { cn } from "@/lib/utils";

const TokenBalance = () => {
  const { balance, isAnonymous, isLoading } = useWallet();

  // Suppress flicker before first fetch resolves; once we know, we
  // always show the chip so users notice the bonus they got.
  if (isLoading || balance === null) {
    return (
      <div className="hidden sm:inline-flex items-center gap-1 px-2 py-1 rounded-full border border-border text-xs text-muted-foreground">
        <Coins className="h-3.5 w-3.5 opacity-50" />
        <span className="opacity-50">…</span>
      </div>
    );
  }

  const lowBalance = balance <= 0;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-full border text-xs sm:text-sm font-medium transition-colors hover:bg-amber-500/10",
            lowBalance
              ? "border-destructive/40 text-destructive"
              : "border-amber-500/40 text-amber-300",
          )}
          aria-label={`${balance} tokens — click for details`}
        >
          <Coins className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
          {balance}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="end"
        className="w-72 text-sm leading-relaxed"
      >
        <p className="mb-2 font-medium">Your tokens</p>
        <p className="text-muted-foreground">
          Generations on this site consume tokens to limit GPU abuse.
        </p>
        {isAnonymous ? (
          <p className="text-muted-foreground mt-2">
            <Link
              to="/auth"
              className="text-primary hover:underline font-medium"
            >
              Sign in
            </Link>{" "}
            to add 200 tokens to your balance.
          </p>
        ) : null}
      </PopoverContent>
    </Popover>
  );
};

export default TokenBalance;
