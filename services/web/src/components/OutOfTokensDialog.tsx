import { Coins, Linkedin, Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface OutOfTokensDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const LINKEDIN_URL = "https://www.linkedin.com/in/artem-vozniuk-ai/";

const OutOfTokensDialog = ({ open, onOpenChange }: OutOfTokensDialogProps) => {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Coins className="h-5 w-5 text-amber-400" />
            You've used all your demo tokens
          </DialogTitle>
          <DialogDescription className="pt-2 leading-relaxed">
            Thanks for trying the demos. This site runs on a fixed GPU
            budget and doesn't yet support top-ups. If you want a custom
            run, drop me a note and I'll bump your balance.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-0 sm:justify-between">
          <div className="flex gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href={LINKEDIN_URL} target="_blank" rel="noopener noreferrer">
                <Linkedin className="mr-2 h-4 w-4" />
                LinkedIn
              </a>
            </Button>
          </div>
          <Button onClick={() => onOpenChange(false)}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default OutOfTokensDialog;
