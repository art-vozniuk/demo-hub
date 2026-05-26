import {
  useState,
  useEffect,
  useCallback,
  useRef,
  useMemo,
} from "react";
import { Activity, Download, Maximize, Minimize, Orbit, Plane } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { RendererUnsupported } from "@/components/RendererUnsupported";
import { RendererCrashed } from "@/components/RendererCrashed";
import { checkWebGpu, type WebGpuStatus } from "@/lib/webgpu";
import {
  captureEngineError,
  rendererBreadcrumb,
  setWebGpuContext,
} from "@/lib/sentry";

/** Minimal scene shape the viewer needs. Catalog scenes (SplatSceneRead)
 *  and transient SHARP results both fit. */
export type SplatViewerScene = {
  slug: string;
  title: string;
  sceneUrl: string;
  cameraEye: number[];
  cameraFwd: number[];
  // Renderer-side scene id (e.g. "gsplat", "glb_viewer"). Defaults to
  // "gsplat" so existing splat callers don't need to change.
  sceneKind?: string;
};

const RENDERER_URL = import.meta.env.VITE_RENDERER_URL as string | undefined;

type RendererModule = Record<string, unknown> & {
  setStatus?: (msg: string) => void;
  onAbort?: (msg: string) => void;
  printErr?: (msg: string) => void;
  print?: (msg: string) => void;
  __sentryHooked?: boolean;
};
type RendererWindow = Window & {
  Module?: RendererModule;
  __splatReady?: boolean;
};

/** Stall watchdog: no progress nor splat-ready in this window ⇒ crash UI. */
const STALL_TIMEOUT_MS = 90_000;
const ENGINE_LOG_CAP = 200;

type CrashState = {
  reason: "abort" | "window-error" | "stall" | "unknown";
  message?: string;
  engineLogTail?: string[];
} | null;

type WebGpuState = { kind: "checking" } | WebGpuStatus;

function buildIframeSrc(base: string, scene: SplatViewerScene): string {
  const params = new URLSearchParams();
  // The renderer's scene-id whitelist only accepts a-z0-9-_; scene.slug
  // (which can include URLs for SHARP) is for React-side cache busting,
  // so pass the renderer kind separately and let it fall back to default.
  params.set("scene", scene.sceneKind ?? "gsplat");
  params.set("scene_url", scene.sceneUrl);
  if (scene.cameraEye.length === 3) params.set("eye", scene.cameraEye.join(","));
  if (scene.cameraFwd.length === 3) params.set("fwd", scene.cameraFwd.join(","));
  try {
    const url = new URL(base, window.location.origin);
    params.forEach((v, k) => url.searchParams.set(k, v));
    return url.toString();
  } catch {
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}${params.toString()}`;
  }
}

function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

type Progress = { loaded: number; total: number } | null;

/** Loading phases the renderer goes through, surfaced by postMessage. */
type LoadPhase = "wasm" | "scene" | "decoding";

type PerfStat = { cur: number; avg: number; max: number };
type PerfData = {
  frame: PerfStat;
  cpuEncode: PerfStat;
  gpuSort: PerfStat;
  gpuRender: PerfStat;
  gpuTotal: PerfStat;
  camEye?: [number, number, number];
  splats: number;
  gpuValid: boolean;
  version?: string;
};

type TimeSeriesEntry = {
  t: number;
  fps: number;
  frame: number;
  sort: number;
  render: number;
  total: number;
  cam: [number, number, number] | null;
};
type SpikeEntry = {
  t: number;
  frame: number;
  sort: number;
  render: number;
  total: number;
  cam: [number, number, number] | null;
};

class PerfRecorder {
  static SAMPLE_CAP = 5000;
  static TS_CAP = 600;
  static SPIKE_CAP = 50;
  static TS_INTERVAL_MS = 1000;

  startedAtWall: Date = new Date();
  startedAtPerf: number = performance.now();

  scene: { slug: string; title: string; sceneUrl: string } | null = null;
  splatCount = 0;
  gpuValid = false;
  framesSeen = 0;
  version = "unknown";
  iframeDpr: number | null = null;

  private frameSamples: number[] = [];
  private cpuEncSamples: number[] = [];
  private gpuSortSamples: number[] = [];
  private gpuRenderSamples: number[] = [];
  private gpuTotalSamples: number[] = [];

  private timeSeries: TimeSeriesEntry[] = [];
  private lastTsAt = -Infinity;

  private spikes: SpikeEntry[] = [];

  setScene(scene: { slug: string; title: string; sceneUrl: string }) {
    this.scene = scene;
  }

  add(perf: PerfData) {
    this.framesSeen++;
    this.splatCount = perf.splats;
    this.gpuValid = perf.gpuValid;
    if (perf.version) this.version = perf.version;

    const pushBounded = (arr: number[], v: number) => {
      arr.push(v);
      if (arr.length > PerfRecorder.SAMPLE_CAP) arr.shift();
    };
    pushBounded(this.frameSamples, perf.frame.cur);
    pushBounded(this.cpuEncSamples, perf.cpuEncode.cur);
    if (perf.gpuValid) {
      pushBounded(this.gpuSortSamples, perf.gpuSort.cur);
      pushBounded(this.gpuRenderSamples, perf.gpuRender.cur);
      pushBounded(this.gpuTotalSamples, perf.gpuTotal.cur);
    }

    const now = performance.now();
    const t = (now - this.startedAtPerf) / 1000;

    if (now - this.lastTsAt >= PerfRecorder.TS_INTERVAL_MS) {
      this.lastTsAt = now;
      this.timeSeries.push({
        t,
        fps: perf.frame.cur > 0 ? 1000 / perf.frame.cur : 0,
        frame: perf.frame.cur,
        sort: perf.gpuSort.cur,
        render: perf.gpuRender.cur,
        total: perf.gpuTotal.cur,
        cam: perf.camEye ?? null,
      });
      if (this.timeSeries.length > PerfRecorder.TS_CAP) this.timeSeries.shift();
    }

    if (perf.frame.avg > 0 && perf.frame.cur > 2 * perf.frame.avg) {
      this.spikes.push({
        t,
        frame: perf.frame.cur,
        sort: perf.gpuSort.cur,
        render: perf.gpuRender.cur,
        total: perf.gpuTotal.cur,
        cam: perf.camEye ?? null,
      });
      if (this.spikes.length > PerfRecorder.SPIKE_CAP) this.spikes.shift();
    }
  }

  build(): string {
    const dur = (performance.now() - this.startedAtPerf) / 1000;
    const fmt = (n: number, w = 6, p = 2) => n.toFixed(p).padStart(w, " ");
    const fmtCam = (c: [number, number, number] | null) =>
      c ? `(${c[0].toFixed(2)},${c[1].toFixed(2)},${c[2].toFixed(2)})` : "—";

    const pct = (arr: number[], q: number): number => {
      if (arr.length === 0) return 0;
      const s = [...arr].sort((a, b) => a - b);
      const i = Math.min(s.length - 1, Math.floor(q * s.length));
      return s[i];
    };
    const stats = (arr: number[]) => ({
      p50: pct(arr, 0.5),
      p90: pct(arr, 0.9),
      p99: pct(arr, 0.99),
      min: arr.length ? Math.min(...arr) : 0,
      max: arr.length ? Math.max(...arr) : 0,
      mean: arr.length ? arr.reduce((s, v) => s + v, 0) / arr.length : 0,
    });

    const fr = stats(this.frameSamples);
    const ce = stats(this.cpuEncSamples);
    const gs = stats(this.gpuSortSamples);
    const gr = stats(this.gpuRenderSamples);
    const gt = stats(this.gpuTotalSamples);

    let out = "";
    out += "=== gsplat perf log ===\n";
    out += `session: ${this.startedAtWall.toISOString()} (${dur.toFixed(1)}s · ${this.framesSeen} frames)\n`;
    out += `renderer: ${this.version}\n`;
    out += `scene:   ${this.scene?.slug ?? "?"} — ${this.scene?.title ?? "?"}\n`;
    out += `splats:  ${this.splatCount.toLocaleString()}\n`;
    out += `gpu timestamp-query: ${this.gpuValid ? "granted" : "unavailable"}\n`;
    if (typeof navigator !== "undefined") {
      out += `ua:      ${navigator.userAgent}\n`;
    }
    if (typeof window !== "undefined") {
      const parentDpr = window.devicePixelRatio;
      const iframeDpr = this.iframeDpr;
      const dprStr =
        iframeDpr !== null && iframeDpr !== parentDpr
          ? `parent DPR ${parentDpr}, iframe DPR ${iframeDpr}`
          : `DPR ${parentDpr}`;
      out += `viewport: ${window.innerWidth}×${window.innerHeight} @ ${dprStr}\n`;
    }

    out += "\n=== summary (entire session) ===\n";
    out += "metric             p50    p90    p99    min    max   mean\n";
    const row = (label: string, s: ReturnType<typeof stats>) =>
      `${label.padEnd(15)}${fmt(s.p50)}${fmt(s.p90)}${fmt(s.p99)}${fmt(s.min)}${fmt(s.max)}${fmt(s.mean)}\n`;
    out += row("frame ms", fr);
    out += row("cpu enc ms", ce);
    if (this.gpuValid) {
      out += row("gpu sort ms", gs);
      out += row("gpu render ms", gr);
      out += row("gpu total ms", gt);
    } else {
      out += "(gpu rows omitted — timestamp-query unavailable)\n";
    }

    out += `\n=== time-series (1 Hz, ${this.timeSeries.length} entries) ===\n`;
    for (const e of this.timeSeries) {
      out +=
        `t=${fmt(e.t, 5, 1)}  fps=${fmt(e.fps, 5, 1)}  ` +
        `frame=${fmt(e.frame, 5, 1)}  sort=${fmt(e.sort, 5, 1)}  ` +
        `render=${fmt(e.render, 5, 1)}  total=${fmt(e.total, 5, 1)}  ` +
        `cam=${fmtCam(e.cam)}\n`;
    }

    out += `\n=== spikes (frame > 2× rolling avg, ${this.spikes.length} entries) ===\n`;
    for (const e of this.spikes) {
      out +=
        `@${fmt(e.t, 6, 1)}s  frame=${fmt(e.frame, 6, 1)}  ` +
        `sort=${fmt(e.sort, 5, 1)}  render=${fmt(e.render, 5, 1)}  ` +
        `total=${fmt(e.total, 5, 1)}  cam=${fmtCam(e.cam)}\n`;
    }
    if (this.spikes.length === 0) out += "(none)\n";

    return out;
  }
}

const PerfOverlay = ({
  perf,
  recorderRef,
}: {
  perf: PerfData | null;
  recorderRef: React.MutableRefObject<PerfRecorder | null>;
}) => {
  const downloadLog = () => {
    const r = recorderRef.current;
    if (!r) return;
    const text = r.build();
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const stamp = new Date()
      .toISOString()
      .replace(/[:T]/g, "-")
      .replace(/\..+$/, "");
    const a = document.createElement("a");
    a.href = url;
    a.download = `gsplat-perf-${stamp}.log`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const Row = ({
    label,
    stat,
    dim,
  }: {
    label: string;
    stat?: PerfStat;
    dim?: boolean;
  }) => {
    const v = stat ?? { cur: 0, avg: 0, max: 0 };
    const fmt = (n: number) => n.toFixed(1).padStart(5, " ");
    return (
      <tr className={dim ? "text-muted-foreground/50" : ""}>
        <td className="pr-3 py-0.5">{label}</td>
        <td className="px-2 py-0.5 text-right tabular-nums">{fmt(v.cur)}</td>
        <td className="px-2 py-0.5 text-right tabular-nums">{fmt(v.avg)}</td>
        <td className="pl-2 py-0.5 text-right tabular-nums">{fmt(v.max)}</td>
      </tr>
    );
  };

  const fps = perf && perf.frame.cur > 0 ? 1000 / perf.frame.cur : 0;

  return (
    <div className="absolute top-3 right-3 z-20 pointer-events-none">
      <div className="rounded-md border border-border bg-background/85 backdrop-blur px-3 py-2 text-xs font-mono shadow-md min-w-[260px]">
        <div className="flex items-center justify-between mb-1">
          <span className="font-semibold">Perf · 5s window</span>
          <span className="text-muted-foreground">
            {fps > 0 ? `${fps.toFixed(0)} fps` : "—"}
          </span>
        </div>
        <table className="w-full">
          <thead>
            <tr className="text-muted-foreground/70">
              <th className="text-left font-normal pr-3 pb-1"></th>
              <th className="text-right font-normal px-2 pb-1">cur</th>
              <th className="text-right font-normal px-2 pb-1">avg</th>
              <th className="text-right font-normal pl-2 pb-1">max</th>
            </tr>
          </thead>
          <tbody>
            <Row label="frame ms" stat={perf?.frame} />
            <Row label="cpu enc ms" stat={perf?.cpuEncode} />
            <Row label="gpu sort ms" stat={perf?.gpuSort} dim={!perf?.gpuValid} />
            <Row
              label="gpu render ms"
              stat={perf?.gpuRender}
              dim={!perf?.gpuValid}
            />
            <Row
              label="gpu total ms"
              stat={perf?.gpuTotal}
              dim={!perf?.gpuValid}
            />
          </tbody>
        </table>
        <div className="mt-1 pt-1 border-t border-border/50 flex justify-between text-muted-foreground">
          <span>splats</span>
          <span className="tabular-nums">
            {(perf?.splats ?? 0).toLocaleString()}
          </span>
        </div>
        <div className="flex justify-between text-muted-foreground">
          <span>build</span>
          <span className="tabular-nums">{perf?.version ?? "—"}</span>
        </div>
        {perf && !perf.gpuValid && (
          <div className="mt-1 text-[10px] text-muted-foreground/70 leading-tight">
            GPU timings unavailable on this device · timestamp-query feature
            not granted by the browser
          </div>
        )}
        <div className="mt-2 pt-1 border-t border-border/50 flex justify-end pointer-events-auto">
          <button
            type="button"
            onClick={downloadLog}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] uppercase tracking-wide text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            title="Download perf log for this session"
          >
            <Download className="h-3 w-3" />
            Download log
          </button>
        </div>
      </div>
    </div>
  );
};

type CameraMode = "orbit" | "fly";

const CameraHelp = ({ mode }: { mode: CameraMode }) => {
  const isCoarse =
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(pointer: coarse)").matches;

  if (isCoarse) {
    return (
      <p className="mt-3 text-xs text-muted-foreground text-center">
        Drag with one finger to orbit · pinch to zoom · let go to snap back
      </p>
    );
  }

  if (mode === "fly") {
    return (
      <p className="mt-3 text-xs text-muted-foreground text-center">
        <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">W A S D</kbd>{" "}
        to move ·{" "}
        <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">Q E</kbd>{" "}
        to rise / fall · hold{" "}
        <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">LMB</kbd>{" "}
        and drag to look · click the orbit icon to snap home
      </p>
    );
  }

  return (
    <p className="mt-3 text-xs text-muted-foreground text-center">
      Drag with the mouse to orbit · scroll to zoom · press{" "}
      <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">W A S D</kbd>{" "}
      (or click the fly icon) to free-fly
    </p>
  );
};

export type SplatViewerProps = {
  /** Scene to load. Identity (slug) drives a fresh mount + state reset. */
  scene: SplatViewerScene;
  /** CSS height for the viewer block. Default 75vh. */
  height?: string;
  /** Render the floating perf overlay toggle. Default true. */
  enablePerf?: boolean;
  /** Show camera-control hint under the viewer. Default true. */
  showCameraHelp?: boolean;
};

/** Self-contained Gaussian-splat scene viewer. Owns WebGPU preflight,
 *  iframe lifecycle, loading overlay, crash detection, optional perf
 *  overlay. Used by /renderer (catalog) and /sharp (transient result). */
export const SplatViewer = ({
  scene,
  height = "75vh",
  enablePerf = true,
  showCameraHelp = true,
}: SplatViewerProps) => {
  const [isReady, setIsReady] = useState(false);
  const [progress, setProgress] = useState<Progress>(null);
  const [phase, setPhase] = useState<LoadPhase>("wasm");
  const [perfOpen, setPerfOpen] = useState(false);
  const [perf, setPerf] = useState<PerfData | null>(null);
  const [webGpu, setWebGpu] = useState<WebGpuState>({ kind: "checking" });
  const [crash, setCrash] = useState<CrashState>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  const lastPerfUpdateRef = useRef(0);
  const recorderRef = useRef<PerfRecorder | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const engineLogRef = useRef<string[]>([]);
  const stallTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [isFullscreen, setIsFullscreen] = useState(false);
  const [cameraMode, setCameraMode] = useState<CameraMode>("orbit");
  // Touch devices stay orbit-only — no keyboard, no fly toggle.
  const isCoarsePointer = useMemo(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(pointer: coarse)").matches,
    [],
  );

  const requestCameraMode = useCallback((mode: CameraMode) => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    iframe.contentWindow?.postMessage(
      { type: "set-camera-mode", mode: mode === "orbit" ? 0 : 1 },
      "*",
    );
  }, []);

  // Mirror Fullscreen API state — covers user-pressed Esc / browser-driven exit.
  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const toggleFullscreen = useCallback(async () => {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
      return;
    }
    const target = wrapperRef.current;
    if (!target) return;
    try {
      await target.requestFullscreen();
    } catch {
      return;
    }
    // Touch devices: try to lock to landscape so the renderer fills the
    // screen properly. Only supported in some browsers (Chrome Android
    // yes, Safari iOS no — silently swallow the rejection there).
    try {
      const orientation = (
        screen as Screen & {
          orientation?: { lock?: (o: string) => Promise<void> };
        }
      ).orientation;
      const isCoarse =
        window.matchMedia &&
        window.matchMedia("(pointer: coarse)").matches;
      if (isCoarse && orientation?.lock) {
        await orientation.lock("landscape");
      }
    } catch {
      /* unsupported / disallowed — leave orientation alone */
    }
  }, []);

  const pushEngineLog = useCallback((line: string) => {
    const buf = engineLogRef.current;
    buf.push(line);
    if (buf.length > ENGINE_LOG_CAP) buf.shift();
  }, []);

  const armStallTimer = useCallback(() => {
    if (stallTimerRef.current) clearTimeout(stallTimerRef.current);
    stallTimerRef.current = setTimeout(() => {
      setCrash(
        (c) =>
          c ?? {
            reason: "stall",
            message: `No engine activity for ${STALL_TIMEOUT_MS / 1000}s`,
            engineLogTail: [...engineLogRef.current],
          },
      );
    }, STALL_TIMEOUT_MS);
  }, []);

  useEffect(() => {
    let alive = true;
    rendererBreadcrumb("webgpu preflight start");
    checkWebGpu().then((status) => {
      if (!alive) return;
      setWebGpu(status);
      setWebGpuContext(status);
      rendererBreadcrumb("webgpu preflight result", { kind: status.kind });
      if (status.kind !== "supported") {
        captureEngineError({
          reason:
            status.kind === "no-api"
              ? "no-webgpu-api"
              : status.kind === "no-adapter"
                ? "no-adapter"
                : "unknown",
          message: `webgpu preflight: ${status.kind}`,
        });
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  const iframeSrc = useMemo(
    () => (RENDERER_URL ? buildIframeSrc(RENDERER_URL, scene) : undefined),
    [scene],
  );

  const checkIfAlreadyReady = useCallback(() => {
    try {
      const iWin = iframeRef.current?.contentWindow as RendererWindow | null;
      if (iWin?.Module?.setStatus && iWin?.__splatReady) setIsReady(true);
    } catch {
      /* cross-origin — ignore */
    }
  }, []);

  // Fresh scene (or retry) — wipe loading state and arm watchdog.
  useEffect(() => {
    setIsReady(false);
    setProgress(null);
    setPhase("wasm");
    setCrash(null);
    engineLogRef.current = [];
    if (stallTimerRef.current) {
      clearTimeout(stallTimerRef.current);
      stallTimerRef.current = null;
    }
    rendererBreadcrumb("scene selected", { slug: scene.slug, title: scene.title });
    armStallTimer();
  }, [scene.slug, retryNonce, armStallTimer, scene.title]);

  useEffect(() => {
    if (!crash) return;
    captureEngineError({
      reason: crash.reason,
      message: crash.message,
      scene: { slug: scene.slug, title: scene.title },
      engineLogTail: crash.engineLogTail,
    });
    if (stallTimerRef.current) {
      clearTimeout(stallTimerRef.current);
      stallTimerRef.current = null;
    }
  }, [crash, scene.slug, scene.title]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    let pollHandle: ReturnType<typeof setInterval> | null = null;
    let cleanups: Array<() => void> = [];

    const onLoad = () => {
      try {
        const win = iframe.contentWindow as RendererWindow | null;
        if (!win) return;

        const onWinError = (e: ErrorEvent) => {
          pushEngineLog(`window error: ${e.message}`);
          setCrash(
            (c) =>
              c ?? {
                reason: "window-error",
                message: e.message,
                engineLogTail: [...engineLogRef.current],
              },
          );
        };
        const onRejection = (e: PromiseRejectionEvent) => {
          const reason = e.reason as { message?: string } | string | undefined;
          const msg =
            typeof reason === "string"
              ? reason
              : reason?.message ?? String(reason ?? "unhandled rejection");
          pushEngineLog(`unhandled rejection: ${msg}`);
          setCrash(
            (c) =>
              c ?? {
                reason: "abort",
                message: msg,
                engineLogTail: [...engineLogRef.current],
              },
          );
        };
        win.addEventListener("error", onWinError);
        win.addEventListener("unhandledrejection", onRejection);
        cleanups.push(() => {
          try {
            win.removeEventListener("error", onWinError);
          } catch {
            /* gone */
          }
          try {
            win.removeEventListener("unhandledrejection", onRejection);
          } catch {
            /* gone */
          }
        });

        // Emscripten installs throwing getters for non-exported runtime
        // methods — skip them or our own onAbort fires from a read probe.
        const safeHook = <K extends "onAbort" | "printErr" | "print">(
          M: Record<string, unknown>,
          key: K,
          wrap: (
            orig: ((msg: string) => void) | undefined,
          ) => (msg: string) => void,
        ) => {
          const desc = Object.getOwnPropertyDescriptor(M, key);
          if (desc && typeof desc.get === "function" && !("value" in desc)) {
            rendererBreadcrumb("module hook skipped (guarded property)", { key });
            return;
          }
          let orig: ((msg: string) => void) | undefined;
          try {
            orig = M[key] as ((msg: string) => void) | undefined;
          } catch {
            rendererBreadcrumb("module hook skipped (read threw)", { key });
            return;
          }
          try {
            (M as Record<string, unknown>)[key] = wrap(orig);
          } catch {
            rendererBreadcrumb("module hook skipped (write threw)", { key });
          }
        };

        pollHandle = setInterval(() => {
          const M = win.Module as
            | undefined
            | (Record<string, unknown> & { __sentryHooked?: boolean });
          if (!M || M.__sentryHooked) return;
          M.__sentryHooked = true;

          safeHook(M, "printErr", (origPrintErr) => (msg) => {
            origPrintErr?.(msg);
            pushEngineLog(msg);
            if (
              /wgpuRequestAdapter failed|No available adapters|Assertion Failed:/i.test(
                msg,
              )
            ) {
              setCrash(
                (c) =>
                  c ?? {
                    reason: "abort",
                    message: msg,
                    engineLogTail: [...engineLogRef.current],
                  },
              );
            }
          });

          safeHook(M, "print", (origPrint) => (msg) => {
            origPrint?.(msg);
            pushEngineLog(msg);
          });

          safeHook(M, "onAbort", (origAbort) => (msg) => {
            origAbort?.(msg);
            pushEngineLog(`abort: ${msg}`);
            setCrash(
              (c) =>
                c ?? {
                  reason: "abort",
                  message: String(msg),
                  engineLogTail: [...engineLogRef.current],
                },
            );
          });

          if (pollHandle) {
            clearInterval(pollHandle);
            pollHandle = null;
          }
        }, 100);
        cleanups.push(() => {
          if (pollHandle) {
            clearInterval(pollHandle);
            pollHandle = null;
          }
        });
      } catch (err) {
        rendererBreadcrumb("iframe contentWindow access failed", {
          error: err instanceof Error ? err.message : String(err),
        });
      }
    };

    iframe.addEventListener("load", onLoad);
    cleanups.push(() => iframe.removeEventListener("load", onLoad));

    return () => {
      cleanups.forEach((fn) => fn());
      cleanups = [];
    };
  }, [scene.slug, retryNonce, pushEngineLog]);

  // Perf recorder lifecycle — opening the overlay starts a fresh session.
  useEffect(() => {
    if (perfOpen) {
      const r = new PerfRecorder();
      r.setScene({
        slug: scene.slug,
        title: scene.title,
        sceneUrl: scene.sceneUrl,
      });
      recorderRef.current = r;
    } else {
      recorderRef.current = null;
    }
  }, [perfOpen, scene.slug, scene.title, scene.sceneUrl]);

  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      const t = e.data?.type;
      if (t === "splat-ready") {
        if (stallTimerRef.current) {
          clearTimeout(stallTimerRef.current);
          stallTimerRef.current = null;
        }
      } else if (
        t === "renderer-ready" ||
        t === "renderer-progress" ||
        t === "splat-progress" ||
        t === "splat-decoding"
      ) {
        armStallTimer();
      }
      if (t === "renderer-ready") {
        setPhase((p) => (p === "wasm" ? "scene" : p));
      } else if (t === "renderer-progress") {
        const loaded = Number(e.data.loaded) || 0;
        const total = Number(e.data.total) || 0;
        if (total <= 0) return;
        setProgress((prev) => {
          if (prev && prev.loaded >= prev.total) return prev;
          return { loaded: Math.min(loaded, total), total };
        });
      } else if (t === "splat-progress") {
        const loaded = Number(e.data.loaded) || 0;
        const total = Number(e.data.total) || 0;
        if (total <= 0) return;
        setPhase("scene");
        setProgress({ loaded: Math.min(loaded, total), total });
      } else if (t === "splat-decoding") {
        setPhase("decoding");
      } else if (t === "splat-ready") {
        try {
          const iWin = iframeRef.current?.contentWindow as RendererWindow | null;
          if (iWin) iWin.__splatReady = true;
        } catch {
          /* cross-origin — ignore */
        }
        setIsReady(true);
      } else if (t === "camera-mode-changed") {
        const mode = e.data?.mode === "fly" ? "fly" : "orbit";
        setCameraMode(mode);
      } else if (t === "perf") {
        const data: PerfData = {
          frame: e.data.frame,
          cpuEncode: e.data.cpuEncode,
          gpuSort: e.data.gpuSort,
          gpuRender: e.data.gpuRender,
          gpuTotal: e.data.gpuTotal,
          camEye:
            Array.isArray(e.data.camEye) && e.data.camEye.length === 3
              ? (e.data.camEye as [number, number, number])
              : undefined,
          splats: Number(e.data.splats) || 0,
          gpuValid: Boolean(e.data.gpuValid),
          version: typeof e.data.version === "string" ? e.data.version : undefined,
        };
        const r = recorderRef.current;
        if (r && r.iframeDpr === null) {
          try {
            const w = iframeRef.current?.contentWindow as Window | null;
            if (w) r.iframeDpr = w.devicePixelRatio;
          } catch {
            /* cross-origin — leave as null */
          }
        }
        r?.add(data);
        const now = performance.now();
        if (now - lastPerfUpdateRef.current < 100) return;
        lastPerfUpdateRef.current = now;
        setPerf(data);
      }
    };
    window.addEventListener("message", handleMessage);

    const poll = setInterval(checkIfAlreadyReady, 500);
    const timeout = setTimeout(() => clearInterval(poll), 60_000);

    return () => {
      window.removeEventListener("message", handleMessage);
      clearInterval(poll);
      clearTimeout(timeout);
    };
  }, [checkIfAlreadyReady, scene.slug, armStallTimer]);

  const progressFraction = progress ? progress.loaded / progress.total : 0;
  const progressPercent = Math.min(100, progressFraction * 100);

  const phaseLabel =
    phase === "decoding"
      ? "Decoding splats & uploading to GPU..."
      : phase === "scene"
        ? `Downloading ${scene.title}...`
        : `Loading renderer...`;

  if (webGpu.kind === "checking") {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-border text-muted-foreground"
        style={{ height }}
      >
        Checking your browser's WebGPU support…
      </div>
    );
  }
  if (webGpu.kind !== "supported") {
    return <RendererUnsupported status={webGpu} />;
  }
  if (!RENDERER_URL) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-border text-muted-foreground"
        style={{ height }}
      >
        Renderer is not configured.
      </div>
    );
  }
  if (crash) {
    return (
      <RendererCrashed
        reason={crash.reason}
        message={crash.message}
        engineLogTail={crash.engineLogTail}
        onRetry={() => {
          setCrash(null);
          setIsReady(false);
          engineLogRef.current = [];
          setRetryNonce((n) => n + 1);
        }}
      />
    );
  }

  return (
    <div className="space-y-3">
      <div
        ref={wrapperRef}
        className="relative w-full bg-background"
        style={{ height: isFullscreen ? "100vh" : height }}
      >
        {enablePerf && perfOpen && isReady && (
          <PerfOverlay perf={perf} recorderRef={recorderRef} />
        )}
        {enablePerf && isReady && (
          <div className="absolute top-3 left-3 z-20">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant={perfOpen ? "default" : "secondary"}
                  size="sm"
                  onClick={() => setPerfOpen((v) => !v)}
                  className="gap-1 h-8 w-8 p-0 rounded-full shadow-md"
                  aria-pressed={perfOpen}
                  aria-label="Toggle perf overlay"
                >
                  <Activity className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">Toggle perf overlay</TooltipContent>
            </Tooltip>
          </div>
        )}
        {isReady && (
          <div className="absolute top-3 right-3 z-20 flex gap-2">
            {!isCoarsePointer && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant={cameraMode === "fly" ? "default" : "secondary"}
                    size="sm"
                    onClick={() =>
                      requestCameraMode(cameraMode === "fly" ? "orbit" : "fly")
                    }
                    className="gap-1 h-8 w-8 p-0 rounded-full shadow-md"
                    aria-pressed={cameraMode === "fly"}
                    aria-label={
                      cameraMode === "fly"
                        ? "Switch to orbit camera"
                        : "Switch to fly camera"
                    }
                  >
                    {cameraMode === "fly" ? (
                      <Orbit className="h-4 w-4" />
                    ) : (
                      <Plane className="h-4 w-4" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  {cameraMode === "fly" ? "Orbit camera" : "Fly camera"}
                </TooltipContent>
              </Tooltip>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={toggleFullscreen}
                  className="gap-1 h-8 w-8 p-0 rounded-full shadow-md"
                  aria-pressed={isFullscreen}
                  aria-label={
                    isFullscreen ? "Exit fullscreen" : "Enter fullscreen"
                  }
                >
                  {isFullscreen ? (
                    <Minimize className="h-4 w-4" />
                  ) : (
                    <Maximize className="h-4 w-4" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                {isFullscreen ? "Exit fullscreen" : "Fullscreen"}
              </TooltipContent>
            </Tooltip>
          </div>
        )}
        {!isReady && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-background z-10 gap-4 px-6">
            <p className="text-sm text-muted-foreground">{phaseLabel}</p>
            <div className="w-72 h-2 bg-muted rounded-full overflow-hidden">
              {progress ? (
                <div
                  className="h-full bg-primary rounded-full transition-[width] duration-300 ease-out"
                  style={{
                    width:
                      phase === "decoding"
                        ? "100%"
                        : `${Math.max(progressPercent, 2)}%`,
                  }}
                />
              ) : (
                <div className="h-full w-1/3 bg-primary/60 rounded-full" />
              )}
            </div>
            <p className="text-xs text-muted-foreground/70 tabular-nums">
              {phase === "decoding"
                ? "Almost there…"
                : progress
                  ? `${formatBytes(progress.loaded)} / ${formatBytes(progress.total)}`
                  : "Connecting..."}
            </p>
          </div>
        )}
        {/* key forces a fresh WASM module on scene switch / retry. */}
        <iframe
          key={`${scene.slug}-${retryNonce}`}
          ref={iframeRef}
          src={iframeSrc}
          className="w-full h-full border-0 outline-none rounded-lg"
          allow="fullscreen"
          title={`Renderer — ${scene.title}`}
        />
      </div>
      {isReady && showCameraHelp && <CameraHelp mode={cameraMode} />}
    </div>
  );
};

export default SplatViewer;
