// Overlay UI for the editor's "Generate splat" flow. State lives in
// GenerationSessionContext; close ≠ cancel (the badge re-opens it).

import { useEffect, useMemo, useState } from "react";
import { Sparkles, RefreshCcw, Check, X } from "lucide-react";

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
import GenerationCard from "@/components/GenerationCard";
import { useGenerationSession } from "@/contexts/GenerationSessionContext";
import { useWallet } from "@/contexts/WalletContext";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// 1x1 transparent PNG — placeholder for GenerationCard when there is no
// init image (fresh T2I). Spinner overlay covers it.
const TRANSPARENT_PX =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

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

  const showCard =
    session.phase === "flux-pending" || session.phase === "flux-ready";
  const cardImageUrl = session.image?.result_url ?? TRANSPARENT_PX;
  const cardGeneratedImage =
    session.phase === "flux-ready" ? session.image?.result_url : undefined;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-primary" />
            Generate splat
          </DialogTitle>
          <DialogDescription className="text-xs">
            {phaseLabel}
          </DialogDescription>
        </DialogHeader>

        <div className="text-[11px] text-muted-foreground flex items-center gap-2 tabular-nums flex-wrap">
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

        {showCard && (
          <div className="w-full max-w-[280px] mx-auto">
            <GenerationCard
              imageUrl={cardImageUrl}
              isProcessing={session.phase === "flux-pending"}
              generatedImage={cardGeneratedImage}
              pipelineId={session.fluxPipelineId}
              estimatedFinishAt={session.estimatedFinishAt}
              workersMissing={session.workersMissing}
            />
          </div>
        )}

        {session.phase !== "sharp-pending" && (
          <div className="space-y-2">
            <Label htmlFor="generate-prompt" className="text-xs">
              Prompt
            </Label>
            <Textarea
              id="generate-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. a small wooden toy train"
              rows={2}
              disabled={session.phase === "flux-pending"}
            />
            {session.phase === "flux-ready" && session.image && (
              <div className="space-y-2 pt-1">
                <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={iterate}
                    onChange={(e) => setIterate(e.target.checked)}
                  />
                  Iterate on this image (img2img)
                </label>
                {iterate && (
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-[11px] text-muted-foreground">
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

        <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
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
          <p className="text-[10px] text-muted-foreground">
            Close keeps the generation running in the background.
            Cancel stops polling — charged tokens are not refunded.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
};
