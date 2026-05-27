// Wizard-style overlay for the editor's "Generate object" flow. Stages:
//   source → (gen-image) → review → (edit) → pick-output → gen-3d
// Each stage shows one decision. State lives in GenerationSessionContext;
// the overlay layers a local `subStep` on top so review/edit/pick-output
// can navigate without changing the session phase.

import { useEffect, useRef, useState } from "react";
import {
  Sparkles,
  RefreshCcw,
  Check,
  ArrowLeft,
  Loader2,
  Pencil,
} from "lucide-react";

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import GenerationCard from "@/components/GenerationCard";
import {
  GenerationSourcePicker,
  type SourceMode,
} from "@/components/generation/GenerationSourcePicker";
import {
  MeshQualityPicker,
  useMeshCost,
} from "@/components/generation/MeshQualityPicker";
import {
  useGenerationSession,
  type OutputKind,
} from "@/contexts/GenerationSessionContext";
import { useWallet } from "@/contexts/WalletContext";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// "review" and "pick-output" are both reached during phase=flux-ready;
// "edit" puts the overlay into refinement mode without changing phase.
type SubStep = "review" | "edit" | "pick-output";
type Submitting = null | "source" | "edit" | "build3d";

// 1x1 transparent PNG — placeholder fed to GenerationCard when there's no
// previous image (fresh text→image run). The card paints a spinner on top.
const TRANSPARENT_PX =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

export const GenerateAssetOverlay = ({ open, onOpenChange }: Props) => {
  const session = useGenerationSession();
  const { balance } = useWallet();

  const [sourceMode, setSourceMode] = useState<SourceMode>("text");
  const [prompt, setPrompt] = useState("");
  const [editPrompt, setEditPrompt] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [subStep, setSubStep] = useState<SubStep>("review");
  const [submitting, setSubmitting] = useState<Submitting>(null);

  const isMesh = session.outputKind === "glb";

  const meshCost = useMeshCost(session.meshSteps, isMesh);

  // Whenever a new image lands, restart on the review screen.
  useEffect(() => {
    if (session.phase === "flux-ready") {
      setSubStep("review");
      setEditPrompt("");
    }
  }, [session.phase, session.image?.result_url]);

  // Auto-close + clear local inputs after the 3D pipeline completes
  // (pollObject → onObjectComplete already calls reset() in the context).
  const prevPhaseRef = useRef(session.phase);
  useEffect(() => {
    const prev = prevPhaseRef.current;
    prevPhaseRef.current = session.phase;
    if (prev === "object-pending" && session.phase === "idle") {
      onOpenChange(false);
    }
  }, [session.phase, onOpenChange]);

  // Re-opening into a clean idle session — wipe leftovers from the
  // previous cycle so the user sees a fresh form.
  useEffect(() => {
    if (open && session.phase === "idle" && !session.image) {
      setPrompt("");
      setEditPrompt("");
      setImageFile(null);
      setSourceMode("text");
      setSubStep("review");
    }
  }, [open, session.phase, session.image]);

  type Stage =
    | "source"
    | "gen-image"
    | "review"
    | "edit"
    | "pick-output"
    | "gen-3d"
    | "failed";
  const stage: Stage = (() => {
    if (session.phase === "object-pending") return "gen-3d";
    if (session.phase === "flux-pending") return "gen-image";
    if (session.phase === "failed") return "failed";
    if (session.phase === "flux-ready") {
      if (subStep === "edit") return "edit";
      if (subStep === "pick-output") return "pick-output";
      return "review";
    }
    return "source";
  })();

  const canStartSource = (() => {
    if (submitting) return false;
    if (sourceMode === "text") {
      if (prompt.trim().length === 0) return false;
      if (balance !== null) {
        const cost = session.fluxCost ?? 0;
        if (balance < cost) return false;
      }
      return true;
    }
    return imageFile !== null;
  })();

  const canApplyEdit = (() => {
    if (submitting) return false;
    if (editPrompt.trim().length === 0) return false;
    if (balance !== null) {
      const cost = session.iterateCost ?? 0;
      if (balance < cost) return false;
    }
    return true;
  })();

  const canBuild3D = (() => {
    if (submitting) return false;
    if (balance !== null) {
      const cost = (isMesh ? meshCost : session.objectCost) ?? 0;
      if (balance < cost) return false;
    }
    return true;
  })();

  const onSourceGenerate = async () => {
    setSubmitting("source");
    try {
      if (sourceMode === "text") {
        await session.start({ prompt, iterate: false });
      } else if (imageFile) {
        await session.startFromImage({ file: imageFile });
      }
    } finally {
      setSubmitting(null);
    }
  };

  const onApplyEdit = async () => {
    setSubmitting("edit");
    try {
      await session.start({ prompt: editPrompt, iterate: true });
    } finally {
      setSubmitting(null);
    }
  };

  const onBuild3D = async () => {
    setSubmitting("build3d");
    try {
      await session.confirm();
    } finally {
      setSubmitting(null);
    }
  };

  // ── Header content per stage ─────────────────────────────────────────
  const header = (() => {
    switch (stage) {
      case "source":
        return {
          title: "Generate object",
          subtitle: "Choose how to provide the source",
          back: null,
        };
      case "gen-image":
        return {
          title: session.iterating ? "Editing image" : "Generating image",
          subtitle: prompt || session.prompt,
          back: () => session.cancel(),
        };
      case "review":
        return {
          title: "Use this image?",
          subtitle: "Confirm to pick a 3D format, or refine the image",
          back: () => session.reset(),
        };
      case "edit":
        return {
          title: "Refine the image",
          subtitle: "Describe what to change",
          back: () => setSubStep("review"),
        };
      case "pick-output":
        return {
          title: "Choose 3D output",
          subtitle: "Mesh is faster; splat is photoreal",
          back: () => setSubStep("review"),
        };
      case "gen-3d":
        return {
          title: isMesh ? "Building mesh…" : "Rendering splat…",
          subtitle: "Runs in the background — you can close this",
          back: null,
        };
      case "failed":
        return {
          title: "Generation failed",
          subtitle: session.errorMessage ?? "Try again",
          back: () => session.reset(),
        };
    }
  })();

  // ── Cost line per stage ──────────────────────────────────────────────
  const costLine = (() => {
    const parts: string[] = [];
    if (
      stage === "source" &&
      sourceMode === "text" &&
      session.fluxCost !== undefined
    ) {
      parts.push(`Image: ${session.fluxCost}`);
    }
    if (stage === "edit" && session.iterateCost !== undefined) {
      parts.push(`Edit: ${session.iterateCost}`);
    }
    if (stage === "pick-output" && !isMesh && session.objectCost !== undefined) {
      // Mesh cost lives inline next to the Quality picker; splat has no
      // quality knob so we keep the header summary.
      parts.push(`Splat: ${session.objectCost}`);
    }
    if (balance !== null) parts.push(`Balance: ${balance}`);
    return parts.join(" · ");
  })();

  // Common wrapper around GenerationCard so each stage can constrain width
  // without touching the card's internal aspect-square layout. FLUX outputs
  // aren't always square — letterbox so the user sees the whole subject.
  const card = (opts: {
    isProcessing: boolean;
    imageUrl: string;
    generatedImage?: string;
    maxW?: string;
  }) => (
    <div className={cn("mx-auto w-full", opts.maxW ?? "max-w-sm")}>
      <GenerationCard
        imageUrl={opts.imageUrl}
        isProcessing={opts.isProcessing}
        generatedImage={opts.generatedImage}
        pipelineId={
          stage === "gen-3d" ? session.objectPipelineId : session.fluxPipelineId
        }
        estimatedFinishAt={session.estimatedFinishAt}
        workersMissing={session.workersMissing}
        objectFit="contain"
      />
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-lg max-h-[90vh] overflow-y-auto"
        hideClose={stage === "gen-image"}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            {header.back && (
              <button
                type="button"
                onClick={header.back}
                className="text-muted-foreground hover:text-foreground -ml-1"
                aria-label="Back"
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
            )}
            <Sparkles className="h-4 w-4 text-primary" />
            {header.title}
          </DialogTitle>
          {header.subtitle && (
            <DialogDescription className="text-xs">
              {header.subtitle}
            </DialogDescription>
          )}
        </DialogHeader>

        {costLine && (
          <div className="text-[11px] text-muted-foreground tabular-nums">
            {costLine}
          </div>
        )}

        {/* ──────────────────── STAGE: source ──────────────────── */}
        {stage === "source" && (
          <GenerationSourcePicker
            sourceMode={sourceMode}
            onSourceModeChange={setSourceMode}
            prompt={prompt}
            onPromptChange={setPrompt}
            imageFile={imageFile}
            onImageFileChange={setImageFile}
            onSubmit={onSourceGenerate}
            canSubmit={canStartSource}
            submitting={submitting === "source"}
          />
        )}

        {/* ──────────────────── STAGE: gen-image ──────────────────── */}
        {stage === "gen-image" &&
          card({
            isProcessing: true,
            // Iterating starts from the current image; fresh runs from blank.
            imageUrl: session.iterating
              ? session.image?.result_url ?? TRANSPARENT_PX
              : TRANSPARENT_PX,
            generatedImage: undefined,
          })}

        {/* ──────────────────── STAGE: review ──────────────────── */}
        {stage === "review" && session.image && (
          <div className="space-y-3">
            {card({
              isProcessing: false,
              imageUrl: session.image.result_url,
            })}
            {session.prompt && !session.imageFromUpload && (
              <div className="text-xs text-muted-foreground italic text-center">
                "{session.prompt}"
              </div>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setSubStep("edit")}
                className="gap-1"
              >
                <Pencil className="h-4 w-4" />
                Edit
              </Button>
              <Button
                size="sm"
                onClick={() => setSubStep("pick-output")}
                className="gap-1"
              >
                <Check className="h-4 w-4" />
                Confirm
              </Button>
            </div>
          </div>
        )}

        {/* ──────────────────── STAGE: edit ──────────────────── */}
        {stage === "edit" && session.image && (
          <div className="space-y-3">
            {card({
              isProcessing: false,
              imageUrl: session.image.result_url,
              maxW: "max-w-xs",
            })}
            <Label htmlFor="edit-prompt" className="text-xs">
              What to change
            </Label>
            <Textarea
              id="edit-prompt"
              value={editPrompt}
              onChange={(e) => setEditPrompt(e.target.value)}
              placeholder="e.g. make the wood lighter, add a chimney"
              rows={3}
              autoFocus
            />
            <div className="flex justify-end pt-1">
              <Button
                size="sm"
                onClick={onApplyEdit}
                disabled={!canApplyEdit}
                className="gap-1"
              >
                {submitting === "edit" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCcw className="h-4 w-4" />
                )}
                Apply edit
              </Button>
            </div>
          </div>
        )}

        {/* ──────────────────── STAGE: pick-output ──────────────────── */}
        {stage === "pick-output" && session.image && (
          <div className="space-y-3">
            {card({
              isProcessing: false,
              imageUrl: session.image.result_url,
              maxW: "max-w-xs",
            })}

            <div className="space-y-1.5">
              <Label htmlFor="output-kind" className="text-xs">
                Output
              </Label>
              <Select
                value={session.outputKind}
                onValueChange={(v) => session.setOutputKind(v as OutputKind)}
              >
                <SelectTrigger id="output-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="glb">GLB mesh · polygons</SelectItem>
                  <SelectItem value="splat">Gaussian splat · gaussians</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {isMesh && (
              <MeshQualityPicker
                value={session.meshSteps}
                onChange={session.setMeshSteps}
                cost={meshCost}
              />
            )}

            <div className="flex justify-end pt-1">
              <Button
                size="sm"
                onClick={onBuild3D}
                disabled={!canBuild3D}
                className="gap-1"
              >
                {submitting === "build3d" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                Build {isMesh ? "mesh" : "splat"}
              </Button>
            </div>
          </div>
        )}

        {/* ──────────────────── STAGE: gen-3d ──────────────────── */}
        {stage === "gen-3d" && session.image && (
          <div className="space-y-3">
            {card({
              isProcessing: true,
              imageUrl: session.image.result_url,
            })}
            <div className="flex justify-end pt-1">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onOpenChange(false)}
              >
                Close
              </Button>
            </div>
          </div>
        )}

        {/* ──────────────────── STAGE: failed ──────────────────── */}
        {stage === "failed" && (
          <div className="space-y-3">
            <div className="text-xs text-destructive">
              {session.errorMessage ?? "Generation failed."}
            </div>
            <div className="flex justify-end">
              <Button size="sm" onClick={() => session.reset()}>
                Start over
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
