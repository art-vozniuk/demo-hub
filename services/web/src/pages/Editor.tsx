import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Upload,
  Trash2,
  AlertCircle,
  Loader2,
  Move,
  RotateCw,
  Maximize2,
  Magnet,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Toggle } from "@/components/ui/toggle";
import { RendererUnsupported } from "@/components/RendererUnsupported";
import { checkWebGpu, type WebGpuStatus } from "@/lib/webgpu";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const RENDERER_URL = import.meta.env.VITE_RENDERER_URL as string | undefined;
const MAX_SPLAT_BYTES = 256 * 1024 * 1024;

type WebGpuState = { kind: "checking" } | WebGpuStatus;
type Tool = "translate" | "rotate" | "scale";

type LoadState =
  | { kind: "idle" }
  | { kind: "uploading"; name: string; size: number }
  | { kind: "loaded"; name: string; size: number; count: number }
  | { kind: "error"; message: string };

type TransformMsg = {
  type: "editor-transform";
  final: boolean;
  drag: boolean;
  tool: Tool;
  axis: number; // -1 / 0=X / 1=Y / 2=Z
  position: [number, number, number];
  rotationDeg: [number, number, number];
  scale: [number, number, number];
};

type SelectionMsg = {
  type: "editor-selection-changed";
  selected: boolean;
  hasContent: boolean;
  count: number;
};

function buildEditorIframeSrc(base: string): string {
  try {
    const url = new URL(base, window.location.origin);
    url.searchParams.set("scene", "editor");
    return url.toString();
  } catch {
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}scene=editor`;
  }
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const AXIS_LABEL = ["X", "Y", "Z"];
const AXIS_COLOR = ["text-red-400", "text-green-400", "text-blue-400"];

const Editor = () => {
  const [webGpu, setWebGpu] = useState<WebGpuState>({ kind: "checking" });
  const [rendererReady, setRendererReady] = useState(false);
  const [load, setLoad] = useState<LoadState>({ kind: "idle" });
  const [dragOver, setDragOver] = useState(false);

  const [tool, setTool] = useState<Tool>("translate");
  const [snap, setSnap] = useState(false);

  const [selection, setSelection] = useState<SelectionMsg | null>(null);
  const [transform, setTransform] = useState<TransformMsg | null>(null);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    checkWebGpu().then((s) => {
      if (alive) setWebGpu(s);
    });
    return () => {
      alive = false;
    };
  }, []);

  // postMessage listener for renderer-side events.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const t = e.data?.type;
      if (t === "renderer-ready" || t === "editor-ready" || t === "splat-ready") {
        setRendererReady(true);
      } else if (t === "editor-splat-loaded") {
        setLoad((prev) =>
          prev.kind === "uploading"
            ? {
                kind: "loaded",
                name: prev.name,
                size: prev.size,
                count: Number(e.data.count) || 0,
              }
            : prev,
        );
        toast.success("Splat loaded");
      } else if (t === "editor-error") {
        const message = String(e.data?.message ?? "Renderer error");
        setLoad({ kind: "error", message });
        toast.error(message);
      } else if (t === "editor-scene-cleared") {
        setLoad({ kind: "idle" });
        setSelection(null);
        setTransform(null);
      } else if (t === "editor-selection-changed") {
        setSelection(e.data as SelectionMsg);
      } else if (t === "editor-transform") {
        setTransform(e.data as TransformMsg);
      } else if (t === "editor-tool-changed") {
        const next = e.data?.tool as Tool;
        if (next === "translate" || next === "rotate" || next === "scale") {
          setTool(next);
        }
      } else if (t === "editor-snap") {
        setSnap(Boolean(e.data?.on));
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const iframeSrc = useMemo(
    () => (RENDERER_URL ? buildEditorIframeSrc(RENDERER_URL) : undefined),
    [],
  );

  const postToIframe = useCallback((msg: unknown, transfer?: Transferable[]) => {
    const w = iframeRef.current?.contentWindow;
    if (!w) return;
    if (transfer) w.postMessage(msg, "*", transfer);
    else w.postMessage(msg, "*");
  }, []);

  // Push tool / snap whenever user toggles them in the UI.
  useEffect(() => {
    if (!rendererReady) return;
    postToIframe({ type: "editor-set-tool", tool });
  }, [tool, rendererReady, postToIframe]);

  useEffect(() => {
    if (!rendererReady) return;
    postToIframe({ type: "editor-set-snap", on: snap });
  }, [snap, rendererReady, postToIframe]);

  const sendSplatBytes = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(".splat")) {
        toast.error("Please pick a .splat file");
        return;
      }
      if (file.size > MAX_SPLAT_BYTES) {
        toast.error(`File too large (${formatBytes(file.size)} > 256 MB cap)`);
        return;
      }

      setLoad({ kind: "uploading", name: file.name, size: file.size });

      let bytes: ArrayBuffer;
      try {
        bytes = await file.arrayBuffer();
      } catch (err) {
        const message = err instanceof Error ? err.message : "Read failed";
        setLoad({ kind: "error", message });
        toast.error(message);
        return;
      }

      postToIframe({ type: "editor-load-splat", bytes }, [bytes]);
    },
    [postToIframe],
  );

  const onFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      e.target.value = "";
      if (f) void sendSplatBytes(f);
    },
    [sendSplatBytes],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files?.[0];
      if (f) void sendSplatBytes(f);
    },
    [sendSplatBytes],
  );

  const onClearClick = useCallback(() => {
    postToIframe({ type: "editor-clear-scene" });
  }, [postToIframe]);

  if (webGpu.kind === "checking") {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-4rem)] text-sm text-muted-foreground">
        Checking your browser's WebGPU support…
      </div>
    );
  }
  if (webGpu.kind !== "supported") {
    return <RendererUnsupported status={webGpu} />;
  }
  if (!RENDERER_URL) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-4rem)] text-sm text-muted-foreground">
        Renderer is not configured.
      </div>
    );
  }

  const hasContent = load.kind === "loaded";

  return (
    <div className="flex h-[calc(100vh-4rem)] w-full bg-background">
      <input
        ref={fileInputRef}
        type="file"
        accept=".splat"
        className="hidden"
        onChange={onFileChange}
      />

      {/* Renderer canvas + HUD overlay. */}
      <div className="relative flex-1 min-w-0 bg-black">
        <iframe
          ref={iframeRef}
          src={iframeSrc}
          className="h-full w-full border-0 outline-none"
          allow="fullscreen"
          title="3D Editor renderer"
        />
        {!rendererReady && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/80 backdrop-blur-sm">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Starting renderer…
            </div>
          </div>
        )}

        {/* Mode hint top-left, helps surface RMB convention. */}
        {rendererReady && (
          <div className="absolute top-3 left-3 px-2.5 py-1 rounded-md bg-background/70 backdrop-blur text-[11px] leading-tight text-muted-foreground pointer-events-none">
            <span className="font-semibold text-foreground/80">Editor mode</span>
            <span className="mx-2">·</span>
            RMB = camera · LMB = select / gizmo
          </div>
        )}

        {/* Drag HUD — only while a drag is in progress. */}
        {transform?.drag && <DragHud t={transform} snap={snap} />}
      </div>

      {/* Right side panel. */}
      <aside className="w-80 shrink-0 border-l border-border bg-card flex flex-col overflow-y-auto">
        <header className="px-4 py-3 border-b border-border">
          <h1 className="text-sm font-semibold tracking-tight">3D Editor</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Splat-first scene editor. GLTF / mesh coming.
          </p>
        </header>

        {/* Drop-area for asset import. */}
        <div className="px-4 pt-4">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            onDragEnter={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragOver={(e) => e.preventDefault()}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            disabled={!rendererReady || load.kind === "uploading"}
            className={cn(
              "w-full rounded-md border-2 border-dashed px-3 py-6 text-center transition-colors outline-none",
              "border-border bg-muted/20 hover:bg-muted/40",
              dragOver && "border-primary bg-primary/10",
              (!rendererReady || load.kind === "uploading") && "opacity-50 cursor-not-allowed",
            )}
          >
            {load.kind === "uploading" ? (
              <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Uploading {load.name}…
              </div>
            ) : (
              <>
                <Upload className="h-5 w-5 mx-auto text-muted-foreground" />
                <div className="mt-2 text-sm font-medium">Drop object</div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  click or drop (.splat)
                </div>
              </>
            )}
          </button>

          {hasContent && (
            <Button
              onClick={onClearClick}
              variant="ghost"
              size="sm"
              className="w-full gap-2 text-muted-foreground mt-2"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear scene
            </Button>
          )}
        </div>

        {/* Toolbar — W/E/R + Snap. */}
        <div className="px-4 pt-4">
          <h2 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
            Tools
          </h2>
          <div className="flex items-center gap-1">
            <ToolButton
              icon={Move}
              label="Move (W)"
              active={tool === "translate"}
              onClick={() => setTool("translate")}
            />
            <ToolButton
              icon={RotateCw}
              label="Rotate (E)"
              active={tool === "rotate"}
              onClick={() => setTool("rotate")}
            />
            <ToolButton
              icon={Maximize2}
              label="Scale (R)"
              active={tool === "scale"}
              onClick={() => setTool("scale")}
            />
            <div className="flex-1" />
            <Toggle
              pressed={snap}
              onPressedChange={setSnap}
              size="sm"
              className="h-8 w-8 p-0"
              title={`Snap ${snap ? "on" : "off"} (hold Ctrl)`}
              aria-label="Toggle snap"
            >
              <Magnet className="h-3.5 w-3.5" />
            </Toggle>
          </div>
          <p className="mt-1.5 text-[10px] text-muted-foreground">
            Snap steps: 0.25 m / 15° / 10 %. Hold Ctrl for momentary snap.
          </p>
        </div>

        <Separator className="mt-4" />

        {/* Inspector. */}
        <section className="px-4 py-3 space-y-3 text-xs">
          <h2 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
            Inspector
          </h2>
          {!hasContent ? (
            <p className="text-muted-foreground">No object loaded.</p>
          ) : !selection?.selected ? (
            <p className="text-muted-foreground">
              Click the object to select. Then use the gizmo or hotkeys.
            </p>
          ) : (
            <InspectorReadout transform={transform} />
          )}
        </section>

        {/* Status. */}
        <div className="px-4 py-3 border-t border-border text-xs text-muted-foreground">
          {load.kind === "loaded" && (
            <div className="space-y-0.5">
              <p className="text-foreground/80 truncate">{load.name}</p>
              <p>
                {load.count.toLocaleString()} splats · {formatBytes(load.size)}
              </p>
            </div>
          )}
          {load.kind === "error" && (
            <div className="flex items-start gap-1.5 text-destructive">
              <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>{load.message}</span>
            </div>
          )}
        </div>

        <div className="mt-auto px-4 py-3 border-t border-border text-[10px] leading-snug text-muted-foreground/70">
          RMB drag = camera · WASD + QE while RMB held = fly · W/E/R = tool ·
          Ctrl = snap
        </div>
      </aside>
    </div>
  );
};

// --- Subcomponents -----------------------------------------------------------

const ToolButton = ({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  active: boolean;
  onClick: () => void;
}) => (
  <button
    type="button"
    onClick={onClick}
    title={label}
    aria-label={label}
    aria-pressed={active}
    className={cn(
      "h-8 w-8 inline-flex items-center justify-center rounded-md border transition-colors",
      active
        ? "bg-primary text-primary-foreground border-primary"
        : "border-border bg-muted/30 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
    )}
  >
    <Icon className="h-3.5 w-3.5" />
  </button>
);

const InspectorReadout = ({ transform }: { transform: TransformMsg | null }) => {
  if (!transform) {
    return <p className="text-muted-foreground">Selected. Drag a gizmo handle.</p>;
  }
  const fmt = (n: number, digits = 3) => n.toFixed(digits);
  return (
    <div className="space-y-2 font-mono text-[11px]">
      <Row label="Position" values={transform.position} fmt={(n) => fmt(n, 3)} unit="m" />
      <Row
        label="Rotation"
        values={transform.rotationDeg}
        fmt={(n) => fmt(n, 1)}
        unit="°"
      />
      <Row label="Scale" values={transform.scale} fmt={(n) => fmt(n, 3)} unit="×" />
    </div>
  );
};

const Row = ({
  label,
  values,
  fmt,
  unit,
}: {
  label: string;
  values: [number, number, number];
  fmt: (n: number) => string;
  unit: string;
}) => (
  <div>
    <div className="text-muted-foreground text-[10px] uppercase tracking-wider mb-0.5">
      {label}
    </div>
    <div className="grid grid-cols-3 gap-1.5">
      {values.map((v, i) => (
        <div
          key={i}
          className={cn(
            "rounded bg-muted/40 px-1.5 py-1 flex items-baseline gap-1 tabular-nums",
          )}
        >
          <span className={cn("text-[9px] font-bold", AXIS_COLOR[i])}>
            {AXIS_LABEL[i]}
          </span>
          <span className="text-foreground/90 truncate">{fmt(v)}</span>
        </div>
      ))}
    </div>
    <div className="text-[9px] text-muted-foreground/60 mt-0.5">{unit}</div>
  </div>
);

const DragHud = ({ t, snap }: { t: TransformMsg; snap: boolean }) => {
  // Show the active value of the axis being dragged. For translate that's
  // the position component along the axis; rotate → rotation degrees;
  // scale → scale factor on that axis.
  if (t.axis < 0 || t.axis > 2) return null;
  const axisName = AXIS_LABEL[t.axis];
  const axisColor = AXIS_COLOR[t.axis];

  let primaryLabel = "";
  let primaryValue = "";
  if (t.tool === "translate") {
    primaryLabel = `${axisName} position`;
    primaryValue = `${t.position[t.axis].toFixed(3)} m`;
  } else if (t.tool === "rotate") {
    primaryLabel = `${axisName} rotation`;
    primaryValue = `${t.rotationDeg[t.axis].toFixed(1)}°`;
  } else {
    primaryLabel = `${axisName} scale`;
    primaryValue = `${t.scale[t.axis].toFixed(3)} ×`;
  }

  return (
    <div className="absolute top-12 left-3 z-20 pointer-events-none">
      <div className="rounded-md border border-border bg-background/85 backdrop-blur px-3 py-2 shadow-lg min-w-[180px]">
        <div className="flex items-baseline gap-2">
          <span className={cn("text-[10px] font-bold", axisColor)}>{axisName}</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
            {t.tool}
          </span>
          {snap && (
            <span className="ml-auto text-[9px] text-primary uppercase">snap</span>
          )}
        </div>
        <div className="mt-1 text-base font-mono font-semibold tabular-nums">
          {primaryValue}
        </div>
        <div className="text-[10px] text-muted-foreground mt-0.5">
          {primaryLabel}
        </div>
      </div>
    </div>
  );
};

export default Editor;
