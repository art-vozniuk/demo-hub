// Standalone Trellis demo: prompt-or-photo → FLUX text→image → review/edit →
// build a GLB mesh → orbit it in the browser. Reuses the editor's
// GenerationSessionContext brain (wired to surface the result here instead of
// inserting into a scene) plus the shared source/quality pickers. Output is
// fixed to GLB — splats are covered by the SHARP demo.

import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Check, Pencil, RefreshCcw, Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { DemoHeader } from "@/components/DemoHeader";
import { SplatViewer, type SplatViewerScene } from "@/components/SplatViewer";
import GenerationCard from "@/components/GenerationCard";
import SharePipelineButton from "@/components/SharePipelineButton";
import {
  GenerationSourcePicker,
  type SourceMode,
} from "@/components/generation/GenerationSourcePicker";
import {
  MeshQualityPicker,
  useMeshCost,
} from "@/components/generation/MeshQualityPicker";
import {
  GenerationSessionProvider,
  useGenerationSession,
} from "@/contexts/GenerationSessionContext";
import { useWallet } from "@/contexts/WalletContext";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";

// 1x1 transparent PNG — placeholder behind the spinner during a fresh
// text→image run, before any image exists.
const TRANSPARENT_PX =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

interface ResultState {
  url: string;
  name: string;
  pipelineId: string | null;
}

type SubStep = "review" | "edit" | "pick-output";
type Submitting = null | "source" | "edit" | "build3d";
type Stage =
  | "source"
  | "gen-image"
  | "review"
  | "edit"
  | "pick-output"
  | "gen-3d"
  | "result"
  | "failed";

const STEPS: { key: "source" | "review" | "build" | "result"; label: string }[] =
  [
    { key: "source", label: "Image" },
    { key: "review", label: "Review" },
    { key: "build", label: "Build" },
    { key: "result", label: "View" },
  ];

const stepForStage = (stage: Stage): (typeof STEPS)[number]["key"] => {
  switch (stage) {
    case "source":
    case "gen-image":
      return "source";
    case "review":
    case "edit":
      return "review";
    case "pick-output":
    case "gen-3d":
      return "build";
    default:
      return "result";
  }
};

const StepIndicator = ({ stage }: { stage: Stage }) => {
  const current = stepForStage(stage);
  const currentIdx = STEPS.findIndex((s) => s.key === current);
  return (
    <div className="flex items-center justify-center gap-2 text-[11px]">
      {STEPS.map((step, i) => {
        const state =
          i < currentIdx ? "done" : i === currentIdx ? "active" : "todo";
        return (
          <div key={step.key} className="flex items-center gap-2">
            <span
              className={cn(
                "inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 font-medium tabular-nums",
                state === "active" && "bg-primary text-primary-foreground",
                state === "done" && "bg-primary/20 text-primary",
                state === "todo" &&
                  "bg-muted text-muted-foreground/70 border border-border",
              )}
            >
              {state === "done" ? <Check className="h-3 w-3" /> : i + 1}
            </span>
            <span
              className={cn(
                state === "active" ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {step.label}
            </span>
            {i < STEPS.length - 1 && (
              <span className="h-px w-5 bg-border" aria-hidden />
            )}
          </div>
        );
      })}
    </div>
  );
};

const TrellisInner = ({
  result,
  clearResult,
}: {
  result: ResultState | null;
  clearResult: () => void;
}) => {
  const session = useGenerationSession();
  const { balance } = useWallet();
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [sourceMode, setSourceMode] = useState<SourceMode>("text");
  const [prompt, setPrompt] = useState("");
  const [editPrompt, setEditPrompt] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [subStep, setSubStep] = useState<SubStep>("review");
  const [submitting, setSubmitting] = useState<Submitting>(null);

  const meshCost = useMeshCost(session.meshSteps, true);

  // A freshly-landed image starts on the review screen.
  useEffect(() => {
    if (session.phase === "flux-ready") {
      setSubStep("review");
      setEditPrompt("");
    }
  }, [session.phase, session.image?.result_url]);

  const stage: Stage = (() => {
    if (result) return "result";
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

  const requireAuth = () => {
    if (user) return true;
    navigate(
      `/auth?redirect=${encodeURIComponent(location.pathname + location.search)}`,
    );
    return false;
  };

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
    if (balance !== null && meshCost !== undefined && balance < meshCost) {
      return false;
    }
    return true;
  })();

  const onSourceGenerate = async () => {
    if (!requireAuth()) return;
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
    if (!requireAuth()) return;
    setSubmitting("edit");
    try {
      await session.start({ prompt: editPrompt, iterate: true });
    } finally {
      setSubmitting(null);
    }
  };

  const onBuild3D = async () => {
    if (!requireAuth()) return;
    setSubmitting("build3d");
    try {
      await session.confirm();
    } finally {
      setSubmitting(null);
    }
  };

  const onTryAnother = () => {
    clearResult();
    session.reset();
    setSourceMode("text");
    setPrompt("");
    setEditPrompt("");
    setImageFile(null);
    setSubStep("review");
  };

  const resultScene: SplatViewerScene | null = result
    ? {
        slug: `trellis-${result.url}`,
        title: result.name || "TRELLIS result",
        sceneUrl: result.url,
        cameraEye: [],
        cameraFwd: [],
        sceneKind: "glb_viewer",
      }
    : null;

  const costLine = (() => {
    const parts: string[] = [];
    if (stage === "source" && sourceMode === "text" && session.fluxCost !== undefined) {
      parts.push(`Image: ${session.fluxCost}`);
    }
    if (stage === "edit" && session.iterateCost !== undefined) {
      parts.push(`Edit: ${session.iterateCost}`);
    }
    if (balance !== null) parts.push(`Balance: ${balance}`);
    return parts.join(" · ");
  })();

  const card = (opts: { isProcessing: boolean; imageUrl: string }) => (
    <div className="mx-auto w-full max-w-sm">
      <GenerationCard
        imageUrl={opts.imageUrl}
        isProcessing={opts.isProcessing}
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
    <section className="max-w-3xl mx-auto space-y-5">
      {stage !== "failed" && <StepIndicator stage={stage} />}

      {!user && stage === "source" && (
        <p className="text-center text-xs text-muted-foreground">
          You'll be asked to sign in to run a generation.
        </p>
      )}

      {["source", "edit", "pick-output"].includes(stage) && costLine && (
        <div className="text-center text-[11px] text-muted-foreground tabular-nums">
          {costLine}
        </div>
      )}

      {/* STAGE: source */}
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

      {/* STAGE: gen-image */}
      {stage === "gen-image" &&
        card({
          isProcessing: true,
          imageUrl: session.iterating
            ? session.image?.result_url ?? TRANSPARENT_PX
            : TRANSPARENT_PX,
        })}

      {/* STAGE: review */}
      {stage === "review" && session.image && (
        <div className="space-y-3">
          {card({ isProcessing: false, imageUrl: session.image.result_url })}
          {session.prompt && !session.imageFromUpload && (
            <div className="text-xs text-muted-foreground italic text-center">
              "{session.prompt}"
            </div>
          )}
          <div className="flex justify-center gap-2 pt-1">
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

      {/* STAGE: edit */}
      {stage === "edit" && session.image && (
        <div className="space-y-3">
          {card({ isProcessing: false, imageUrl: session.image.result_url })}
          <div className="mx-auto w-full max-w-sm space-y-3">
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
            <div className="flex justify-between gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSubStep("review")}
              >
                Back
              </Button>
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
        </div>
      )}

      {/* STAGE: pick-output */}
      {stage === "pick-output" && session.image && (
        <div className="space-y-3">
          {card({ isProcessing: false, imageUrl: session.image.result_url })}
          <div className="mx-auto w-full max-w-sm space-y-3">
            <MeshQualityPicker
              value={session.meshSteps}
              onChange={session.setMeshSteps}
              cost={meshCost}
            />
            <div className="flex justify-between gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSubStep("review")}
              >
                Back
              </Button>
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
                Build mesh
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* STAGE: gen-3d */}
      {stage === "gen-3d" && session.image && (
        <div className="space-y-3">
          {card({ isProcessing: true, imageUrl: session.image.result_url })}
          <p className="text-center text-xs text-muted-foreground">
            Building your mesh — this runs on a serverless GPU.
          </p>
        </div>
      )}

      {/* STAGE: result */}
      {stage === "result" && resultScene && (
        <div className="flex flex-col gap-3">
          <SplatViewer scene={resultScene} height="60vh" />
          <div className="flex flex-wrap items-center justify-center gap-3 text-xs text-muted-foreground">
            <a
              href={resultScene.sceneUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
            >
              Download .glb
            </a>
            <span>•</span>
            <Button
              size="sm"
              variant="outline"
              onClick={onTryAnother}
              className="h-7"
            >
              Make another
            </Button>
            {result?.pipelineId && (
              <>
                <span>•</span>
                <SharePipelineButton
                  pipelineId={result.pipelineId}
                  pipelineDisplayName="TRELLIS"
                  variant="compact"
                />
              </>
            )}
          </div>
        </div>
      )}

      {/* STAGE: failed */}
      {stage === "failed" && (
        <div className="space-y-3 max-w-sm mx-auto">
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            {session.errorMessage ?? "Generation failed."}
          </div>
          <div className="flex justify-end">
            <Button size="sm" onClick={onTryAnother}>
              Start over
            </Button>
          </div>
        </div>
      )}
    </section>
  );
};

const Trellis = () => {
  const [result, setResult] = useState<ResultState | null>(null);

  return (
    <main className="container mx-auto px-6 py-16 space-y-12 min-h-[calc(100vh-8rem)]">
      <DemoHeader
        title="Trellis"
        description="Turn a prompt or a photo into a downloadable 3D GLB mesh you can orbit in your browser. Generate the source image with FLUX or bring your own, then build the mesh on a serverless GPU — async dispatch worker, RabbitMQ orchestration."
        tagline="Describe it or upload a photo"
      />

      <GenerationSessionProvider
        outputBucket="media"
        onAssetReady={({ url, name, pipelineId }) =>
          setResult({ url, name, pipelineId })
        }
      >
        <TrellisInner result={result} clearResult={() => setResult(null)} />
      </GenerationSessionProvider>
    </main>
  );
};

export default Trellis;
