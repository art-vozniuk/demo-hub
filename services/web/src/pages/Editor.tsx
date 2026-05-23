import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Upload, Trash2, AlertCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { RendererUnsupported } from "@/components/RendererUnsupported";
import { checkWebGpu, type WebGpuStatus } from "@/lib/webgpu";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const RENDERER_URL = import.meta.env.VITE_RENDERER_URL as string | undefined;
const MAX_SPLAT_BYTES = 256 * 1024 * 1024; // 256 MB — generous upper bound.

type WebGpuState = { kind: "checking" } | WebGpuStatus;
type LoadState =
  | { kind: "idle" }
  | { kind: "uploading"; name: string; size: number }
  | { kind: "loaded"; name: string; size: number; count: number }
  | { kind: "error"; message: string };

/** Build the iframe URL for the editor scene. Scene id pinned to "editor". */
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

const Editor = () => {
  const [webGpu, setWebGpu] = useState<WebGpuState>({ kind: "checking" });
  const [rendererReady, setRendererReady] = useState(false);
  const [load, setLoad] = useState<LoadState>({ kind: "idle" });

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // WebGPU preflight — same as SplatViewer; without it the iframe will
  // boot, fail at adapter request, and crash with a noisy log.
  useEffect(() => {
    let alive = true;
    checkWebGpu().then((status) => {
      if (alive) setWebGpu(status);
    });
    return () => {
      alive = false;
    };
  }, []);

  // Receive renderer-ready + load result echoes from the iframe.
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
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const iframeSrc = useMemo(
    () => (RENDERER_URL ? buildEditorIframeSrc(RENDERER_URL) : undefined),
    [],
  );

  const onLoadClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const onFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = ""; // allow re-selecting the same file
      if (!file) return;

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

      const iframeWin = iframeRef.current?.contentWindow;
      if (!iframeWin) {
        const message = "Renderer iframe not ready";
        setLoad({ kind: "error", message });
        toast.error(message);
        return;
      }

      // Transfer the ArrayBuffer instead of structured-cloning it —
      // avoids a memcpy of multi-MB files into the iframe heap.
      iframeWin.postMessage({ type: "editor-load-splat", bytes }, "*", [bytes]);
    },
    [],
  );

  const onClearClick = useCallback(() => {
    iframeRef.current?.contentWindow?.postMessage(
      { type: "editor-clear-scene" },
      "*",
    );
  }, []);

  if (webGpu.kind === "checking") {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-8rem)] text-sm text-muted-foreground">
        Checking your browser's WebGPU support…
      </div>
    );
  }
  if (webGpu.kind !== "supported") {
    return <RendererUnsupported status={webGpu} />;
  }
  if (!RENDERER_URL) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-8rem)] text-sm text-muted-foreground">
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

      {/* Renderer canvas — snapped left, takes everything until the
          fixed-width tools panel on the right. */}
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
      </div>

      {/* Right side: tool panel. Single Load button for now; structured
          like a sidebar so it can grow (sections for hierarchy, inspector,
          asset library) without a layout rewrite. */}
      <aside className="w-72 shrink-0 border-l border-border bg-card flex flex-col">
        <header className="px-4 py-3 border-b border-border">
          <h1 className="text-sm font-semibold tracking-tight">3D Editor</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Drop in a Gaussian-splat scene to start.
          </p>
        </header>

        <div className="px-4 py-4 space-y-3">
          <Button
            onClick={onLoadClick}
            disabled={!rendererReady || load.kind === "uploading"}
            className="w-full gap-2"
          >
            {load.kind === "uploading" ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Uploading…
              </>
            ) : (
              <>
                <Upload className="h-4 w-4" />
                Load splat (.splat)
              </>
            )}
          </Button>

          {hasContent && (
            <Button
              onClick={onClearClick}
              variant="ghost"
              className="w-full gap-2 text-muted-foreground"
            >
              <Trash2 className="h-4 w-4" />
              Clear scene
            </Button>
          )}
        </div>

        <Separator />

        <section className="px-4 py-4 space-y-2 text-xs text-muted-foreground">
          <h2 className="text-xs font-medium text-foreground/80 uppercase tracking-wider">
            Status
          </h2>
          {load.kind === "idle" && (
            <p>Empty scene. Use Load to bring in a .splat asset.</p>
          )}
          {load.kind === "uploading" && (
            <p className="text-foreground/80">
              Uploading <span className="font-mono">{load.name}</span> (
              {formatBytes(load.size)})…
            </p>
          )}
          {load.kind === "loaded" && (
            <div className="space-y-1">
              <p className="text-foreground/90 font-medium">{load.name}</p>
              <p>
                {load.count.toLocaleString()} splats ·{" "}
                {formatBytes(load.size)}
              </p>
            </div>
          )}
          {load.kind === "error" && (
            <div
              className={cn(
                "flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5",
                "text-destructive",
              )}
            >
              <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span className="leading-snug">{load.message}</span>
            </div>
          )}
        </section>

        <div className="mt-auto px-4 py-3 border-t border-border text-[10px] leading-snug text-muted-foreground/70">
          Fly camera: WASD + QE · drag LMB to look · Tab returns to orbit
          around content centroid.
        </div>
      </aside>
    </div>
  );
};

export default Editor;
