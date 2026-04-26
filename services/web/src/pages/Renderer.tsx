import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Github, Activity, Download } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAnalytics } from "@/hooks/useAnalytics";
import { ExpandableDescription } from "@/components/ExpandableDescription";
import { splatsApi, SplatSceneRead } from "@/api";

const RENDERER_URL = import.meta.env.VITE_RENDERER_URL as string | undefined;

/**
 * Build the iframe src with the runtime params the renderer needs:
 *   ?scene=<slug>      — telemetry / debugging label
 *   ?scene_url=<url>   — fetched at runtime via emscripten_fetch
 *   ?eye=x,y,z         — initial camera position
 *   ?fwd=x,y,z         — initial camera forward (look direction)
 */
function buildIframeSrc(base: string, scene: SplatSceneRead): string {
  const params = new URLSearchParams();
  params.set("scene", scene.slug);
  params.set("scene_url", scene.scene_url);
  params.set("eye", scene.camera_eye.join(","));
  params.set("fwd", scene.camera_fwd.join(","));
  try {
    const url = new URL(base, window.location.origin);
    params.forEach((v, k) => url.searchParams.set(k, v));
    return url.toString();
  } catch {
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}${params.toString()}`;
  }
}

/** Human-readable byte size, e.g. 1536000 → "1.5 MB". */
function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

type Progress = { loaded: number; total: number } | null;

/**
 * The viewer goes through three serial loading phases that all surface
 * progress through the same overlay:
 *   - "wasm"      — Emscripten preloads Sandbox.data + boots the WASM
 *                   module. After moving train.splat to S3 this is small.
 *   - "scene"     — emscripten_fetch downloads the .splat blob from S3.
 *                   This is the dominant phase for large scenes (~30 MB).
 *   - "decoding"  — splat is in memory, being parsed and uploaded to GPU
 *                   buffers. No byte-level progress here — fixed label.
 * `splat-ready` from the C++ side flips the gate to render-mode.
 */
type LoadPhase = "wasm" | "scene" | "decoding";

/**
 * Perf metrics blob from the renderer iframe (see PerfMetrics::Emit on
 * the C++ side). Each timing entry is in milliseconds; gpuValid is false
 * when the device didn't grant the timestamp-query feature, in which
 * case the GPU rows are zero and shouldn't be displayed.
 */
type PerfStat = { cur: number; avg: number; max: number };
type PerfData = {
  frame: PerfStat;
  cpuEncode: PerfStat;
  gpuSort: PerfStat;
  gpuRender: PerfStat;
  gpuTotal: PerfStat;
  // Camera eye in world space, streamed each frame so the perf log can
  // correlate stutters with where the user was looking. May be missing
  // on older renderer builds — overlay handles the absence.
  camEye?: [number, number, number];
  splats: number;
  gpuValid: boolean;
  // Renderer git short-sha baked at build time. Lets us tell at a
  // glance which prod build a downloaded log came from.
  version?: string;
};


/**
 * Bounded session-perf recorder — collects rolling samples while the
 * perf overlay is open, produces a small text dump on demand. Three
 * data shapes inside, all bounded to keep the eventual file < ~10 KB:
 *
 *   - raw samples (per metric, ring of N=5000)  → percentiles on dump
 *   - 1 Hz time-series snapshot                 → ring of N=600 entries
 *   - frame spikes (frame > 2× session avg)     → ring of N=50
 *
 * Reset on overlay re-open so each "open → fly around → click download"
 * is a clean session.
 */
type TimeSeriesEntry = {
  t: number; // seconds since session start
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
  // The DPR effective inside the iframe, measured once at first
  // sample. Useful to verify the touch-device DPR cap actually applied
  // (parent window's DPR is the device default; we want the after-cap
  // value the renderer is rasterising at).
  iframeDpr: number | null = null;

  // Bounded sample arrays. Push uses Array#shift() once cap is hit —
  // O(N) but rare (every ~500ms at 10 Hz throttle), fine for this scale.
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

    // Spike: this frame's interval exceeded 2× the renderer's own 5s
    // average. perf.frame.avg is fresh per frame, so the threshold
    // adapts to whatever the user was doing recently.
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
    const fmt = (n: number, w = 6, p = 2) =>
      n.toFixed(p).padStart(w, " ");
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
    out += row("frame ms",  fr);
    out += row("cpu enc ms", ce);
    if (this.gpuValid) {
      out += row("gpu sort ms",   gs);
      out += row("gpu render ms", gr);
      out += row("gpu total ms",  gt);
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

/**
 * Floating perf table laid over the iframe. Shows a 5-second rolling
 * window of per-frame timings — current, average, max — for the four
 * GPU phases the renderer instruments plus CPU encode + total frame
 * interval. Honest about its limits: when the device hasn't granted
 * the timestamp-query feature, the GPU rows are dim and explicit
 * about being unavailable.
 */
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
            <Row label="frame ms"   stat={perf?.frame} />
            <Row label="cpu enc ms" stat={perf?.cpuEncode} />
            <Row
              label="gpu sort ms"
              stat={perf?.gpuSort}
              dim={!perf?.gpuValid}
            />
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

/**
 * Camera-control instructions, swapped at runtime depending on the
 * primary input. Touch devices get the joystick legend; everywhere else
 * gets the WASD/QE legend (matches the desktop FlyCamera bindings).
 */
const CameraHelp = () => {
  const isCoarse =
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(pointer: coarse)").matches;

  if (isCoarse) {
    return (
      <p className="mt-3 text-xs text-muted-foreground text-center">
        Drag the left stick to fly · drag the right stick to look ·{" "}
        <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">▲</kbd>{" "}
        <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">▼</kbd>{" "}
        to ascend / descend
      </p>
    );
  }

  return (
    <p className="mt-3 text-xs text-muted-foreground text-center">
      Hold{" "}
      <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">LMB</kbd>{" "}
      and use{" "}
      <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">
        W A S D
      </kbd>{" "}
      to move,{" "}
      <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-xs">Q E</kbd>{" "}
      to rise / fall
    </p>
  );
};

const Renderer = () => {
  const [scenes, setScenes] = useState<SplatSceneRead[]>([]);
  const [scenesError, setScenesError] = useState<string | null>(null);
  const [selected, setSelected] = useState<SplatSceneRead | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [progress, setProgress] = useState<Progress>(null);
  const [phase, setPhase] = useState<LoadPhase>("wasm");
  const [perfOpen, setPerfOpen] = useState(false);
  const [perf, setPerf] = useState<PerfData | null>(null);
  // Throttle UI updates to ~10 Hz (the iframe posts ~60 Hz). Avoids
  // unnecessary re-renders when the panel is open.
  const lastPerfUpdateRef = useRef(0);
  // Recorder is non-null only while the overlay is open — so opening
  // the panel = "start a fresh debug session", closing = "discard".
  // Lives in a ref so the message handler closure always sees the
  // current instance without re-binding.
  const recorderRef = useRef<PerfRecorder | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { track } = useAnalytics();

  // Initial scene list fetch.
  useEffect(() => {
    let alive = true;
    splatsApi
      .getScenes()
      .then((list) => {
        if (alive) setScenes(list);
      })
      .catch((err) => {
        if (alive) setScenesError(err?.message ?? "Failed to load scenes");
      });
    return () => {
      alive = false;
    };
  }, []);

  const iframeSrc = useMemo(
    () =>
      RENDERER_URL && selected
        ? buildIframeSrc(RENDERER_URL, selected)
        : undefined,
    [selected],
  );

  /** Fast path: detect "already ready" if the iframe finished loading before
   *  the message listener was installed (common on cached reloads). */
  const checkIfAlreadyReady = useCallback(() => {
    try {
      const iWin = iframeRef.current?.contentWindow as any;
      // We can only assume readiness when both the WASM runtime AND the
      // splat fetch are done. The latter signals via `__splatReady` flag
      // (set when the iframe posts splat-ready — see below).
      if (iWin?.Module?.setStatus && iWin?.__splatReady) setIsReady(true);
    } catch {
      // cross-origin — ignore
    }
  }, []);

  // Reset loading state when the user picks a (different) scene.
  useEffect(() => {
    setIsReady(false);
    setProgress(null);
    setPhase("wasm");
  }, [selected?.slug]);

  // Recorder lifecycle — opening the perf overlay starts a fresh
  // debug session; closing it (or switching scene) drops the recorder
  // and any half-collected data.
  useEffect(() => {
    if (perfOpen && selected) {
      const r = new PerfRecorder();
      r.setScene({
        slug:     selected.slug,
        title:    selected.title,
        sceneUrl: selected.scene_url,
      });
      recorderRef.current = r;
    } else {
      recorderRef.current = null;
    }
  }, [perfOpen, selected?.slug]);

  useEffect(() => {
    if (!selected) return;
    const handleMessage = (e: MessageEvent) => {
      const t = e.data?.type;
      if (t === "renderer-ready") {
        // WASM module booted; splat is still downloading. Move into the
        // scene phase but keep the overlay up.
        setPhase((p) => (p === "wasm" ? "scene" : p));
      } else if (t === "renderer-progress") {
        // Sandbox.data preload (small now). Drives the bar in "wasm" phase.
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
        // Stamp a flag inside the iframe so the cached-reload poll in
        // checkIfAlreadyReady can recognise an already-finished session.
        try {
          const iWin = iframeRef.current?.contentWindow as any;
          if (iWin) iWin.__splatReady = true;
        } catch {
          /* cross-origin — ignore */
        }
        setIsReady(true);
      } else if (t === "perf") {
        const data: PerfData = {
          frame:     e.data.frame,
          cpuEncode: e.data.cpuEncode,
          gpuSort:   e.data.gpuSort,
          gpuRender: e.data.gpuRender,
          gpuTotal:  e.data.gpuTotal,
          camEye:    Array.isArray(e.data.camEye) && e.data.camEye.length === 3
                       ? (e.data.camEye as [number, number, number])
                       : undefined,
          splats:    Number(e.data.splats) || 0,
          gpuValid:  Boolean(e.data.gpuValid),
          version:   typeof e.data.version === "string" ? e.data.version : undefined,
        };
        // Capture the iframe-side DPR once; it's the post-cap value the
        // renderer actually rasterises at (parent's window.devicePixelRatio
        // is the device default before our override).
        const r = recorderRef.current;
        if (r && r.iframeDpr === null) {
          try {
            const w = iframeRef.current?.contentWindow as Window | null;
            if (w) r.iframeDpr = w.devicePixelRatio;
          } catch {
            /* cross-origin — leave as null */
          }
        }
        // Recorder gets EVERY frame so percentiles + spikes are honest.
        // setPerf for the UI is throttled separately to ~10 Hz.
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
  }, [checkIfAlreadyReady, selected?.slug]);

  const progressFraction = progress ? progress.loaded / progress.total : 0;
  const progressPercent = Math.min(100, progressFraction * 100);

  const phaseLabel =
    phase === "decoding"
      ? "Decoding splats & uploading to GPU..."
      : phase === "scene"
        ? `Downloading ${selected?.title ?? "scene"}...`
        : `Loading renderer...`;

  return (
    <main className="container mx-auto px-6 py-16 space-y-8 min-h-[calc(100vh-8rem)]">
      <section className="max-w-4xl mx-auto space-y-6 text-center animate-fade-in">
        <div className="space-y-4">
          <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
            <span className="text-gradient">3D Renderer</span>
          </h1>
          <ExpandableDescription>
            Real-time Gaussian Splatting renderer. Custom C++ engine on
            WebGPU with per-frame GPU radix sort and EWA splat projection
            in WGSL. Compiled to WebAssembly via Emscripten.
          </ExpandableDescription>
          <div className="flex items-center justify-center gap-3">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  className="rounded-full animate-pulse-glow"
                  asChild
                >
                  <a
                    href="https://github.com/art-vozniuk/renderer"
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label="GitHub Repository"
                    onClick={() =>
                      track({ name: "renderer_github_repo_clicked", params: {} })
                    }
                  >
                    <Github className="h-5 w-5" />
                  </a>
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p>Visit the repository</p>
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </section>

      <div className="max-w-5xl mx-auto space-y-3">
        {!RENDERER_URL ? (
          <div className="flex items-center justify-center rounded-lg border border-border text-muted-foreground h-96">
            Renderer is not configured.
          </div>
        ) : !selected ? (
          // ----- Grid view -----
          <div className="space-y-4">
            {scenesError && (
              <div className="text-sm text-destructive text-center">
                {scenesError}
              </div>
            )}
            {scenes.length === 0 && !scenesError ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="aspect-video rounded-lg bg-muted/40 animate-pulse"
                  />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {scenes.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => {
                      track({
                        name: "renderer_scene_opened",
                        params: { scene_slug: s.slug },
                      });
                      setSelected(s);
                    }}
                    className="group text-left rounded-lg overflow-hidden border border-border bg-muted/20 hover:bg-muted/40 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <div className="aspect-video w-full overflow-hidden bg-black">
                      <img
                        src={s.image_url}
                        alt={s.title}
                        loading="lazy"
                        className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                      />
                    </div>
                    <div className="p-3 space-y-1">
                      <h3 className="font-semibold tracking-tight">{s.title}</h3>
                      {s.description && (
                        <p className="text-xs text-muted-foreground line-clamp-2">
                          {s.description}
                        </p>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          // ----- Render view -----
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  track({
                    name: "renderer_scene_back",
                    params: { scene_slug: selected.slug },
                  });
                  setSelected(null);
                }}
                className="gap-1"
              >
                <ArrowLeft className="h-4 w-4" />
                Back to scenes
              </Button>
              <div className="flex items-center gap-2">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant={perfOpen ? "default" : "ghost"}
                      size="sm"
                      onClick={() => setPerfOpen((v) => !v)}
                      className="gap-1"
                      aria-pressed={perfOpen}
                      aria-label="Toggle perf overlay"
                    >
                      <Activity className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    <p>Toggle perf overlay</p>
                  </TooltipContent>
                </Tooltip>
                <div className="text-sm text-muted-foreground">{selected.title}</div>
              </div>
            </div>

            <div className="relative w-full" style={{ height: "75vh" }}>
              {perfOpen && isReady && (
                <PerfOverlay perf={perf} recorderRef={recorderRef} />
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
              {/* key={selected.slug} forces remount on scene switch so the
               *   WASM module restarts cleanly with the new ?scene_url=. */}
              <iframe
                key={selected.slug}
                ref={iframeRef}
                src={iframeSrc}
                className="w-full h-full border-0 outline-none"
                allow="fullscreen"
                title={`Renderer — ${selected.title}`}
              />
            </div>

            {isReady && <CameraHelp />}
          </div>
        )}
      </div>
    </main>
  );
};

export default Renderer;
