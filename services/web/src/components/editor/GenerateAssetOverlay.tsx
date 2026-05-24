// Overlay UI for the editor's "Generate object" flow. State lives in
// GenerationSessionContext; close ≠ cancel (the badge re-opens it). An
// output toggle picks the second stage: GLB mesh (default) or splat.

import { useEffect, useMemo, useState } from "react";
import { Sparkles, RefreshCcw, Check } from "lucide-react";

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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import GenerationCard from "@/components/GenerationCard";
import {
  useGenerationSession,
  type OutputKind,
} from "@/contexts/GenerationSessionContext";
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

  const isMesh = session.outputKind === "glb";

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
    if (session.phase === "flux-pending" || session.phase === "object-pending") {
      return false;
    }
    if (balance !== null) {
      const required = iterate
        ? session.iterateCost ?? 0
        : session.fluxCost ?? 0;
      if (balance < required) return false;
    }
    return true;
  }, [prompt, session.phase, session.fluxCost, session.iterateCost, balance, iterate]);

  const onGenerate = async () => {
    await session.start({ prompt, iterate });
  };

  const onConfirm = async () => {
    await session.confirm();
    onOpenChange(false);
  };

  const phaseLabel = (() => {
    switch (session.phase) {
      case "flux-pending":
        return session.iterating ? "Editing image…" : "Generating image…";
      case "object-pending":
        return isMesh
          ? "Building mesh (background)…"
          : "Rendering splat (background)…";
      case "flux-ready":
        return isMesh
          ? "Image ready — confirm to build a GLB mesh"
          : "Image ready — confirm to render a splat";
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
      <DialogContent
        className="sm:max-w-md max-h-[85vh] overflow-y-auto"
        hideClose
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-primary" />
            Generate object
          </DialogTitle>
          <DialogDescription className="text-xs">
            {phaseLabel}
          </DialogDescription>
        </DialogHeader>

        <div className="text-[11px] text-muted-foreground flex items-center gap-2 tabular-nums flex-wrap">
          {(() => {
            const imageCost = iterate ? session.iterateCost : session.fluxCost;
            return imageCost !== undefined && (
              <span>{iterate ? "Edit" : "Image"}: {imageCost}</span>
            );
          })()}
          {session.objectCost !== undefined && (
            <span>{isMesh ? "Mesh" : "Splat"}: {session.objectCost}</span>
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

        {session.phase !== "object-pending" && (
          <div className="space-y-2">
            <div className="space-y-1.5">
              <Label className="text-xs">Output</Label>
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                value={session.outputKind}
                onValueChange={(v) => {
                  if (v) session.setOutputKind(v as OutputKind);
                }}
                className="justify-start"
              >
                <ToggleGroupItem value="glb" className="text-[11px] px-3">
                  GLB mesh
                </ToggleGroupItem>
                <ToggleGroupItem value="splat" className="text-[11px] px-3">
                  Gaussian splat
                </ToggleGroupItem>
              </ToggleGroup>
            </div>
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
              <label className="flex items-center gap-2 text-[11px] text-muted-foreground pt-1">
                <input
                  type="checkbox"
                  checked={iterate}
                  onChange={(e) => setIterate(e.target.checked)}
                />
                Edit this image (use the prompt to refine it)
              </label>
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
              {isMesh ? "Confirm & build mesh" : "Confirm & render splat"}
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
                  ? "Edit"
                  : "Generate new"
                : "Generate"}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};
