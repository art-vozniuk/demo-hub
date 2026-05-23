import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Eye,
  EyeOff,
  Plus,
  Loader2,
  Trash2,
} from "lucide-react";
import { RendererUnsupported } from "@/components/RendererUnsupported";
import { checkWebGpu, type WebGpuStatus } from "@/lib/webgpu";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const RENDERER_URL = import.meta.env.VITE_RENDERER_URL as string | undefined;
const MAX_SPLAT_BYTES = 256 * 1024 * 1024;

// Fire-and-forget dev log — Vite middleware appends to
// services/external/renderer/dev.log and echoes to its terminal.
function devLog(tag: string, ...parts: unknown[]) {
  if (!import.meta.env.DEV) return;
  try {
    const msg = parts
      .map((p) => (typeof p === "string" ? p : JSON.stringify(p)))
      .join(" ");
    fetch("/__dev_log", {
      method: "POST",
      headers: { "content-type": "text/plain" },
      body: `[${tag}] ${msg}`,
      keepalive: true,
    }).catch(() => {});
  } catch {
    /* never throw from logging */
  }
}

type WebGpuState = { kind: "checking" } | WebGpuStatus;

type SceneObject = {
  id: number;
  name: string;
  visible: boolean;
  count: number;
};

type TransformMsg = {
  type: "editor-transform";
  final: boolean;
  drag: boolean;
  kind: "translate" | "rotate" | "scale" | "none";
  axis: number;
  id: number;
  position: [number, number, number];
  rotationDeg: [number, number, number];
  scale: [number, number, number];
};

const AXIS_COLOR = ["text-rose-400", "text-emerald-400", "text-sky-400"];

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

const Editor = () => {
  const [webGpu, setWebGpu] = useState<WebGpuState>({ kind: "checking" });
  const [rendererReady, setRendererReady] = useState(false);
  const [objects, setObjects] = useState<SceneObject[]>([]);
  const [selectedId, setSelectedId] = useState<number>(0);
  const [transform, setTransform] = useState<TransformMsg | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [uploadingCount, setUploadingCount] = useState(0);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  // WebGPU preflight.
  useEffect(() => {
    let alive = true;
    checkWebGpu().then((s) => {
      if (alive) setWebGpu(s);
    });
    return () => {
      alive = false;
    };
  }, []);

  // postMessage listener.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const t = e.data?.type;
      if (t && typeof t === "string" && (t.startsWith("editor-") || t.startsWith("renderer-") || t === "splat-ready")) {
        devLog(
          "react.in",
          t,
          t === "editor-objects" ? `n=${e.data.objects?.length ?? 0}` : "",
          t === "editor-selection-changed" ? `id=${e.data.id}` : "",
          t === "editor-transform" ? `final=${e.data.final} drag=${e.data.drag}` : "",
        );
      }
      if (t === "renderer-ready" || t === "editor-ready" || t === "splat-ready") {
        setRendererReady(true);
      } else if (t === "editor-objects") {
        setObjects((e.data.objects as SceneObject[]) ?? []);
      } else if (t === "editor-selection-changed") {
        setSelectedId(Number(e.data.id) || 0);
      } else if (t === "editor-transform") {
        setTransform(e.data as TransformMsg);
      } else if (t === "editor-error") {
        toast.error(String(e.data?.message ?? "Renderer error"));
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const iframeSrc = useMemo(
    () => (RENDERER_URL ? buildEditorIframeSrc(RENDERER_URL) : undefined),
    [],
  );

  const postToIframe = useCallback(
    (msg: unknown, transfer?: Transferable[]) => {
      const w = iframeRef.current?.contentWindow;
      const m = msg as { type?: string; id?: number; name?: string; bytes?: ArrayBuffer };
      devLog(
        "react.out",
        m?.type ?? "?",
        m?.id !== undefined ? `id=${m.id}` : "",
        m?.name !== undefined ? `name=${m.name}` : "",
        m?.bytes ? `bytes=${m.bytes.byteLength}` : "",
        w ? "" : "(no iframe!)",
      );
      if (!w) return;
      try {
        if (transfer) w.postMessage(msg, "*", transfer);
        else w.postMessage(msg, "*");
        devLog("react.out.ok", m?.type ?? "?");
      } catch (err) {
        devLog("react.out.error", m?.type ?? "?", String(err));
      }
    },
    [],
  );

  const sendSplatFile = useCallback(
    async (file: File) => {
      devLog("react.file", `name=${file.name} size=${file.size}`);
      if (!file.name.toLowerCase().endsWith(".splat")) {
        if (file.name.toLowerCase().endsWith(".glb")) {
          toast.error(".glb is coming — splat only for now");
        } else {
          toast.error(`Unsupported file: ${file.name}`);
        }
        return;
      }
      if (file.size > MAX_SPLAT_BYTES) {
        toast.error(`File too large: ${file.name}`);
        return;
      }
      setUploadingCount((c) => c + 1);
      try {
        const bytes = await file.arrayBuffer();
        postToIframe(
          { type: "editor-load-splat", bytes, name: file.name },
          [bytes],
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : "Read failed";
        toast.error(message);
      } finally {
        setUploadingCount((c) => Math.max(0, c - 1));
      }
    },
    [postToIframe],
  );

  const sendFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      devLog("react.send.start", `n=${list.length}`);
      for (const f of list) {
        try {
          // eslint-disable-next-line no-await-in-loop
          await sendSplatFile(f);
        } catch (err) {
          devLog("react.send.error", String(err));
        }
      }
      devLog("react.send.end");
    },
    [sendSplatFile],
  );

  const onPickFiles = useCallback(() => {
    devLog("react.pick", `input=${fileInputRef.current ? "ok" : "null"}`);
    fileInputRef.current?.click();
  }, []);

  const onFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const inputEl = e.target;
      // Snapshot the FileList into a stable array BEFORE clearing the
      // input — Chrome mutates the live FileList in-place when value="".
      const snapshot = inputEl.files ? Array.from(inputEl.files) : [];
      devLog("react.input.change", `n=${snapshot.length}`);
      if (snapshot.length > 0) void sendFiles(snapshot);
      inputEl.value = "";
    },
    [sendFiles],
  );

  // Whole-page drag-drop (panel + iframe). We count enter/leave events
  // because dragleave fires when crossing into the iframe and the
  // single-flag heuristic gets stuck if files are dropped over the
  // iframe (which intercepts the drop in its own document if we're
  // not careful).
  useEffect(() => {
    let depth = 0;
    const onDragEnter = (e: DragEvent) => {
      e.preventDefault();
      depth += 1;
      setDragOver(true);
    };
    const onDragOver = (e: DragEvent) => {
      e.preventDefault();
    };
    const onDragLeave = (e: DragEvent) => {
      e.preventDefault();
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragOver(false);
    };
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      depth = 0;
      setDragOver(false);
      const files = e.dataTransfer?.files;
      devLog("react.drop", `files=${files?.length ?? 0}`);
      if (files && files.length > 0) void sendFiles(files);
    };
    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [sendFiles]);

  // Delete shortcut when focus is inside the panel.
  const onPanelKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (renamingId !== null) return;
      if (e.key === "Delete") {
        if (selectedId) postToIframe({ type: "editor-delete-object", id: selectedId });
      } else if (e.key === "F2") {
        const o = objects.find((x) => x.id === selectedId);
        if (o) startRename(o);
      }
    },
    [renamingId, selectedId, objects, postToIframe],
  );

  const startRename = useCallback((o: SceneObject) => {
    setRenamingId(o.id);
    setRenameDraft(o.name);
    requestAnimationFrame(() => renameInputRef.current?.select());
  }, []);

  const commitRename = useCallback(() => {
    if (renamingId === null) return;
    const name = renameDraft.trim();
    if (name) {
      postToIframe({ type: "editor-rename-object", id: renamingId, name });
    }
    setRenamingId(null);
  }, [renamingId, renameDraft, postToIframe]);

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

  const selected = objects.find((o) => o.id === selectedId) ?? null;

  return (
    <div className="flex h-[calc(100vh-4rem)] w-full bg-background">
      <input
        ref={fileInputRef}
        type="file"
        accept=".splat"
        multiple
        className="hidden"
        onChange={onFileInputChange}
      />

      {/* Renderer canvas + global drop indicator. */}
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
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Starting renderer…
            </div>
          </div>
        )}
        {dragOver && (
          <div className="absolute inset-0 pointer-events-none border-2 border-dashed border-primary/60 bg-primary/10 rounded-md flex items-center justify-center">
            <div className="text-sm text-foreground/90 font-medium">
              Drop .splat to add to scene
            </div>
          </div>
        )}
        {transform?.drag && transform.kind !== "none" && (
          <DragHud t={transform} />
        )}
      </div>

      {/* Right panel — Scene on top, Transform below. */}
      <aside
        tabIndex={0}
        onKeyDown={onPanelKeyDown}
        className="w-72 shrink-0 border-l border-border bg-card flex flex-col overflow-hidden outline-none"
      >
        {/* Scene section. */}
        <div className="flex flex-col min-h-0">
          <SectionHeader title="Scene" subtitle={objects.length ? `${objects.length}` : undefined} />
          <div className="overflow-y-auto max-h-[55vh] border-b border-border/60">
            {objects.length === 0 && (
              <div className="px-3 py-3 text-[11px] text-muted-foreground/80">
                No objects. Drop a .splat file anywhere, or click + below.
              </div>
            )}
            {objects.map((o) => {
              const isSel = o.id === selectedId;
              const isRen = renamingId === o.id;
              return (
                <div
                  key={o.id}
                  onClick={() => postToIframe({ type: "editor-select-object", id: o.id })}
                  onDoubleClick={() => {
                    if (isRen) return;
                    postToIframe({ type: "editor-focus-object", id: o.id });
                  }}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1 cursor-pointer text-[11px] leading-tight",
                    "hover:bg-muted/40",
                    isSel && "bg-primary/20 text-foreground",
                    !o.visible && !isSel && "text-muted-foreground/60",
                  )}
                >
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      postToIframe({
                        type: "editor-set-visibility",
                        id: o.id,
                        visible: !o.visible,
                      });
                    }}
                    className="text-muted-foreground/80 hover:text-foreground"
                    aria-label={o.visible ? "Hide" : "Show"}
                  >
                    {o.visible ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                  </button>
                  {isRen ? (
                    <input
                      ref={renameInputRef}
                      value={renameDraft}
                      onChange={(e) => setRenameDraft(e.target.value)}
                      onBlur={commitRename}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitRename();
                        if (e.key === "Escape") setRenamingId(null);
                        e.stopPropagation();
                      }}
                      onClick={(e) => e.stopPropagation()}
                      className="flex-1 min-w-0 bg-transparent border border-primary/60 px-1 py-0 text-[11px] outline-none"
                    />
                  ) : (
                    <span
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        startRename(o);
                      }}
                      className="flex-1 min-w-0 truncate"
                      title={o.name}
                    >
                      {o.name}
                    </span>
                  )}
                  <span className="text-[10px] tabular-nums text-muted-foreground/80 shrink-0">
                    {o.count > 0 ? `${(o.count / 1000).toFixed(0)}k` : ""}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      postToIframe({ type: "editor-delete-object", id: o.id });
                    }}
                    className="text-muted-foreground/60 hover:text-destructive"
                    aria-label="Delete"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              );
            })}
            {/* Add object row. */}
            <div
              onClick={onPickFiles}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 cursor-pointer text-[11px] leading-tight",
                "text-muted-foreground hover:bg-muted/40 hover:text-foreground border-t border-border/40",
                uploadingCount > 0 && "opacity-60 pointer-events-none",
              )}
            >
              {uploadingCount > 0 ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Plus className="h-3 w-3" />
              )}
              <span className="flex-1">
                {uploadingCount > 0 ? `Loading ${uploadingCount}…` : "Add object"}
              </span>
              <span className="text-[10px] text-muted-foreground/70">.splat, .glb</span>
            </div>
          </div>
        </div>

        {/* Transform section — only when selection exists. */}
        {selected && (
          <div className="flex flex-col min-h-0">
            <SectionHeader title="Transform" />
            <div className="px-3 py-1.5 space-y-1">
              <TransformRow
                label="Position"
                values={transform?.position ?? [0, 0, 0]}
                digits={2}
                onCommit={(next) => {
                  if (!transform) return;
                  postToIframe({
                    type: "editor-set-transform",
                    id: selected.id,
                    position: next,
                    rotationDeg: transform.rotationDeg,
                    scale: transform.scale,
                  });
                }}
              />
              <TransformRow
                label="Rotation"
                values={transform?.rotationDeg ?? [0, 0, 0]}
                digits={1}
                onCommit={(next) => {
                  if (!transform) return;
                  postToIframe({
                    type: "editor-set-transform",
                    id: selected.id,
                    position: transform.position,
                    rotationDeg: next,
                    scale: transform.scale,
                  });
                }}
              />
              <TransformRow
                label="Scale"
                values={transform?.scale ?? [1, 1, 1]}
                digits={2}
                onCommit={(next) => {
                  if (!transform) return;
                  postToIframe({
                    type: "editor-set-transform",
                    id: selected.id,
                    position: transform.position,
                    rotationDeg: transform.rotationDeg,
                    scale: next,
                  });
                }}
              />
            </div>
          </div>
        )}
      </aside>
    </div>
  );
};

// --- Subcomponents -----------------------------------------------------------

const SectionHeader = ({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) => (
  <div className="flex items-baseline justify-between px-3 py-1.5 border-b border-border/60">
    <h2 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
      {title}
    </h2>
    {subtitle && (
      <span className="text-[10px] text-muted-foreground/70 tabular-nums">{subtitle}</span>
    )}
  </div>
);

const TransformRow = ({
  label,
  values,
  digits,
  onCommit,
}: {
  label: string;
  values: [number, number, number];
  digits: number;
  onCommit: (next: [number, number, number]) => void;
}) => (
  <div className="flex items-baseline gap-1.5 text-[11px] leading-tight font-mono tabular-nums">
    <span className="text-muted-foreground w-[58px] shrink-0 font-sans not-italic">
      {label}
    </span>
    {values.map((v, i) => (
      <NumberField
        key={i}
        value={v}
        digits={digits}
        axis={i}
        onCommit={(nv) => {
          const next: [number, number, number] = [values[0], values[1], values[2]];
          next[i] = nv;
          onCommit(next);
        }}
      />
    ))}
  </div>
);

const NumberField = ({
  value,
  digits,
  axis,
  onCommit,
}: {
  value: number;
  digits: number;
  axis: number;
  onCommit: (n: number) => void;
}) => {
  const [draft, setDraft] = useState<string>(value.toFixed(digits));
  const [focused, setFocused] = useState(false);

  // Sync external updates when not actively editing.
  useEffect(() => {
    if (!focused) setDraft(value.toFixed(digits));
  }, [value, digits, focused]);

  const commit = () => {
    const parsed = parseFloat(draft);
    if (Number.isFinite(parsed) && parsed !== value) onCommit(parsed);
    else setDraft(value.toFixed(digits));
  };

  return (
    <div className="flex items-baseline gap-0.5 flex-1 min-w-0 rounded px-1 bg-muted/30 focus-within:bg-muted/60 focus-within:ring-1 focus-within:ring-primary/40">
      <span className={cn("text-[9px] font-bold shrink-0", AXIS_COLOR[axis])}>
        {"XYZ"[axis]}
      </span>
      <input
        type="text"
        inputMode="decimal"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onFocus={(e) => {
          setFocused(true);
          e.currentTarget.select();
        }}
        onBlur={() => {
          setFocused(false);
          commit();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            (e.currentTarget as HTMLInputElement).blur();
          } else if (e.key === "Escape") {
            setDraft(value.toFixed(digits));
            (e.currentTarget as HTMLInputElement).blur();
          }
        }}
        className="w-full min-w-0 bg-transparent text-foreground/95 outline-none truncate"
      />
    </div>
  );
};

const DragHud = ({ t }: { t: TransformMsg }) => {
  if (t.axis < 0 || t.axis > 2) return null;
  const axisCol = AXIS_COLOR[t.axis];
  let primary = "";
  let secondary = "";
  if (t.kind === "translate") {
    primary = `${t.position[t.axis].toFixed(3)} m`;
    secondary = `${"XYZ"[t.axis]} position`;
  } else if (t.kind === "rotate") {
    primary = `${t.rotationDeg[t.axis].toFixed(1)}°`;
    secondary = `${"XYZ"[t.axis]} rotation`;
  } else {
    primary = `${t.scale[t.axis].toFixed(3)}×`;
    secondary = `${"XYZ"[t.axis]} scale`;
  }
  return (
    <div className="absolute top-3 left-3 z-20 pointer-events-none">
      <div className="rounded-md border border-border bg-background/85 backdrop-blur px-2.5 py-1.5 shadow-md">
        <div className="flex items-baseline gap-1.5">
          <span className={cn("text-[9px] font-bold", axisCol)}>{"XYZ"[t.axis]}</span>
          <span className="text-[9px] uppercase tracking-wider text-muted-foreground">
            {t.kind}
          </span>
        </div>
        <div className="text-sm font-mono font-semibold tabular-nums leading-tight">
          {primary}
        </div>
        <div className="text-[9px] text-muted-foreground mt-0.5">{secondary}</div>
      </div>
    </div>
  );
};

export default Editor;
