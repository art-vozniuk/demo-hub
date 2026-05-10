import { Coins, Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";

interface InsufficientTokensDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  cost: number;
  balance: number;
}

const InsufficientTokensDialog = ({
  open,
  onOpenChange,
  cost,
  balance,
}: InsufficientTokensDialogProps) => {
  const { signInWithGoogle } = useAuth();
  const [isSigningIn, setIsSigningIn] = useState(false);

  const handleSignIn = async () => {
    setIsSigningIn(true);
    try {
      // Pass current path so OAuth round-trip lands the user back on
      // the same Generate screen with their photo / preset still selected.
      await signInWithGoogle(window.location.pathname + window.location.search);
    } catch (err) {
      console.error(err);
      toast.error("Failed to sign in. Please try again.");
      setIsSigningIn(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Coins className="h-5 w-5 text-amber-400" />
            Need {cost} tokens, you have {balance}
          </DialogTitle>
          <DialogDescription className="pt-2 leading-relaxed">
            Sign in with Google to add 200 tokens to your balance and keep
            generating. Free, no card required.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={isSigningIn}
          >
            Maybe later
          </Button>
          <Button onClick={handleSignIn} disabled={isSigningIn}>
            {isSigningIn ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Signing in...
              </>
            ) : (
              "Sign in with Google"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default InsufficientTokensDialog;
