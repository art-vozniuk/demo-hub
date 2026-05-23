import { Link, useLocation } from "react-router-dom";
import { Coins } from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useAuth } from "@/contexts/AuthContext";
import { useWallet } from "@/contexts/WalletContext";
import { cn } from "@/lib/utils";

const TokenBalance = () => {
  const { user } = useAuth();
  const { balance, signupGrant, isLoading } = useWallet();
  const location = useLocation();
  const authHref = `/auth?redirect=${encodeURIComponent(location.pathname + location.search)}`;

  // Suppress flicker before first fetch resolves; once we know, we
  // always show the chip so users notice their balance.
  if (isLoading || balance === null) {
    return (
      <div className="hidden sm:inline-flex items-center gap-1 px-2 py-1 rounded-full border border-border text-xs text-muted-foreground">
        <Coins className="h-3.5 w-3.5 opacity-50" />
        <span className="opacity-50">…</span>
      </div>
    );
  }

  const isSignedIn = !!user;
  const lowBalance = isSignedIn && balance <= 0;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-full border text-xs sm:text-sm font-medium transition-colors hover:bg-primary/10",
            lowBalance
              ? "border-destructive/40 text-destructive"
              : "border-primary/40 text-primary",
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
          This is a personal projects site — everything here is completely
          free. Tokens exist only to prevent GPU abuse on generations.
        </p>
        {!isSignedIn && signupGrant !== null ? (
          <p className="text-muted-foreground mt-2">
            Please{" "}
            <Link
              to={authHref}
              className="text-primary hover:underline font-medium"
            >
              sign in
            </Link>{" "}
            to get {signupGrant} tokens.
          </p>
        ) : null}
      </PopoverContent>
    </Popover>
  );
};

export default TokenBalance;
