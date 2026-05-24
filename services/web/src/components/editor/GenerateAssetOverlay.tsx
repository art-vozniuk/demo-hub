// Overlay UI for the editor's "Generate splat" flow. State lives in
// GenerationSessionContext; close ≠ cancel (the badge re-opens it).

import { useEffect, useMemo, useState } from "react";
import { Loader2, Sparkles, RefreshCcw, Check, X } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { useGenerationSession } from "@/contexts/GenerationSessionContext";
import { useWallet } from "@/contexts/WalletContext";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export const GenerateAssetOverlay = ({ open, onOpenChange }: Props) => {
  const session = useGenerationSession();
  const { balance } = useWallet();

  const [prompt, setPrompt] = useState("");
  const [iterate, setIterate] = useState(false);
  const [strength, setStrength] = useState(0.7);

  // Pre-fill from the running session when re-opening from the badge.
  useEffect(() => {
    if (open && session.prompt && !prompt) {
      setPrompt(session.prompt);
    }
  }, [open, session.prompt, prompt]);

  useEffect(() => {
    if (session.phase === "idle") {
      setIterate(false);
    }
  }, [session.phase]);

  const canStart = useMemo(() => {
    if (prompt.trim().length === 0) return false;
    if (session.phase === "flux-pending" || session.phase === "sharp-pending") {
      return false;
    }
    if (session.totalCost !== undefined && balance !== null) {
      const required = iterate ? session.fluxCost ?? 0 : session.totalCost;
      if (balance < required) return false;
    }
    return true;
  }, [prompt, session.phase, session.totalCost, session.fluxCost, balance, iterate]);

  const onGenerate = async () => {
    await session.start({ prompt, iterate, strength });
  };

  const onConfirm = async () => {
    await session.confirm();
    // Sharp runs in the background — the badge surfaces progress.
    onOpenChange(false);
  };

  const onCancelClick = () => {
    session.cancel();
    setPrompt("");
    setIterate(false);
    onOpenChange(false);
  };

  const phaseLabel = (() => {
    switch (session.phase) {
      case "flux-pending":
        return session.iterating ? "Iterating on image…" : "Generating image…";
      case "sharp-pending":
        return "Rendering splat (background)…";
      case "flux-ready":
        return "Image ready — confirm to render as splat";
      case "failed":
        return session.errorMessage ?? "Generation failed";
      default:
        return "Describe the object you want to generate";
    }
  })();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            Generate splat
          </DialogTitle>
          <DialogDescription>{phaseLabel}</DialogDescription>
        </DialogHeader>

        <div className="text-xs text-muted-foreground flex items-center gap-3 tabular-nums">
          {session.fluxCost !== undefined && (
            <span>Image: {session.fluxCost}</span>
          )}
          {session.sharpCost !== undefined && (
            <span>Splat: {session.sharpCost}</span>
          )}
          {session.totalCost !== undefined && (
            <span className="text-foreground/90">
              Total: {session.totalCost}
            </span>
          )}
          {balance !== null && <span>· Balance: {balance}</span>}
        </div>

        {(session.phase === "flux-pending" ||
          session.phase === "flux-ready" ||
          session.phase === "sharp-pending") && (
          <div className="aspect-square w-full rounded-lg border border-border bg-muted/20 overflow-hidden flex items-center justify-center relative">
            {session.image?.result_url && (
              <img
                src={session.image.result_url}
                alt="generated"
                className="w-full h-full object-contain"
              />
            )}
            {(session.phase === "flux-pending" ||
              session.phase === "sharp-pending") && (
              <div className="absolute inset-0 bg-background/60 backdrop-blur-sm flex items-center justify-center">
                <div className="flex items-center gap-2 text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {session.phase === "flux-pending"
                    ? "Generating image…"
                    : "Rendering splat…"}
                </div>
              </div>
            )}
          </div>
        )}

        {session.phase !== "sharp-pending" && (
          <div className="space-y-2">
            <Label htmlFor="generate-prompt">Prompt</Label>
            <Textarea
              id="generate-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. a small wooden toy train"
              rows={3}
              disabled={session.phase === "flux-pending"}
            />
            {session.phase === "flux-ready" && session.image && (
              <div className="space-y-2 pt-1">
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={iterate}
                    onChange={(e) => setIterate(e.target.checked)}
                  />
                  Iterate on this image (img2img)
                </label>
                {iterate && (
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>Strength</span>
                      <span className="tabular-nums">{strength.toFixed(2)}</span>
                    </div>
                    <Slider
                      value={[strength]}
                      onValueChange={(v) => setStrength(v[0])}
                      min={0.3}
                      max={0.95}
                      step={0.05}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2 pt-2">
          {session.phase === "flux-ready" && (
            <Button
              variant="default"
              size="sm"
              onClick={onConfirm}
              className="gap-1"
            >
              <Check className="h-4 w-4" />
              Confirm & render splat
            </Button>
          )}
          {(session.phase === "idle" ||
            session.phase === "flux-ready" ||
            session.phase === "failed") && (
            <Button
              variant={session.phase === "flux-ready" ? "secondary" : "default"}
              size="sm"
              onClick={onGenerate}
              disabled={!canStart}
              className="gap-1"
            >
              {session.phase === "flux-ready" ? (
                <RefreshCcw className="h-4 w-4" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              {session.phase === "flux-ready"
                ? iterate
                  ? "Iterate"
                  : "Generate new"
                : "Generate"}
            </Button>
          )}
          {(session.phase === "flux-pending" ||
            session.phase === "sharp-pending" ||
            session.phase === "flux-ready") && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onCancelClick}
              className="gap-1"
            >
              <X className="h-4 w-4" />
              Cancel
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onOpenChange(false)}
          >
            Close
          </Button>
        </div>
        {(session.phase === "flux-pending" ||
          session.phase === "sharp-pending") && (
          <p className="text-[11px] text-muted-foreground">
            Closing this dialog keeps the generation running in the
            background. Cancelling stops polling — tokens already
            charged are not refunded.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
};
