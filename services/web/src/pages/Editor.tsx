import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Eye,
  EyeOff,
  Plus,
  Loader2,
  Trash2,
  Save,
  FolderOpen,
  Check,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { RendererUnsupported } from "@/components/RendererUnsupported";
import { checkWebGpu, type WebGpuStatus } from "@/lib/webgpu";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";
import { editorScenesApi, ApiError, type EditorSceneListItem } from "@/api";
import {
  eulerDegToQuat,
  extOf,
  forwardToQuat,
  quatToEulerDeg,
  quatToForward,
  sha256Hex,
  type ManifestAsset,
  type ManifestObject,
  type ObjectKind,
  type SceneManifest,
  type Vec3Tuple,
} from "@/lib/scene-manifest";
import {
  clearRestorePayload,
  loadRestorePayload,
  saveRestorePayload,
  type SceneBytesMap,
} from "@/lib/editor-idb";
import { uploadToS3 } from "@/lib/s3";

const RENDERER_URL = import.meta.env.VITE_RENDERER_URL as string | undefined;
const MAX_SPLAT_BYTES = 256 * 1024 * 1024;
const ASSET_BUCKET = "media";
const ASSET_KEY_PREFIX = "editor-assets";

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
  // Optional fields surfaced by the renderer for non-splat objects. The
  // current renderer (splats only) doesn't send these; Agent A adds them
  // for meshes/lights. Treat absence as "splat".
  kind?: "splat" | "mesh" | "light_directional";
  light?: { color: [number, number, number]; intensity: number };
};

// Local entry tracking per-object asset/transform state that we need at
// Save time. URLs survive across saves so we can skip re-upload; bytes
// only exist for objects added in this session.
type AssetEntry = {
  name: string;            // display name (matches renderer-side, stripped)
  filename: string;        // original filename with extension — used for S3 key ext
  size: number;
  bytes?: ArrayBuffer;
  sha256?: string;
  url?: string;
};

// Cache of latest known transform per object id, updated on every
// editor-transform message. Save reads from here.
type TransformCache = Record<number, {
  position: Vec3Tuple;
  rotationDeg: Vec3Tuple;
  scale: Vec3Tuple;
}>;

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
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [webGpu, setWebGpu] = useState<WebGpuState>({ kind: "checking" });
  const [rendererReady, setRendererReady] = useState(false);
  const [objects, setObjects] = useState<SceneObject[]>([]);
  const [selectedId, setSelectedId] = useState<number>(0);
  const [transform, setTransform] = useState<TransformMsg | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [uploadingCount, setUploadingCount] = useState(0);

  // Scene metadata.
  const [sceneId, setSceneId] = useState<string | null>(null);
  const [sceneName, setSceneName] = useState<string>("Untitled");
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState<string>("Untitled");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sceneList, setSceneList] = useState<EditorSceneListItem[]>([]);
  // Set true once we've decided whether to auto-load — prevents the
  // effect from firing twice (e.g. on user→sceneList state churn).
  const autoLoadHandledRef = useRef(false);
  // Names of objects that the hydrate flow is currently fetching/parsing
  // (one entry per pending object, kept in FIFO order). Surfaces as ghost
  // rows + a viewport pill so the user sees the slow asset download.
  const [loadingPlaceholders, setLoadingPlaceholders] = useState<
    { name: string; kind: ObjectKind }[]
  >([]);

  // Camera state — synced with the C++ side via editor-camera-pose. Treated
  // as a singleton "object" in the scene panel (kind=camera, id sentinel = -1).
  const [cameraPose, setCameraPose] = useState<{ position: Vec3Tuple; forward: Vec3Tuple }>({
    position: [0, 2.5, 6],
    forward: [0, -0.25, -1],
  });
  const [cameraSelected, setCameraSelected] = useState(false);
  // Last camera pose at the most recent successful save. Anything different
  // → dirty. Updated by hydrate (initial pose loaded) and Save.
  const lastSavedCameraRef = useRef<{ position: Vec3Tuple; forward: Vec3Tuple } | null>(null);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);

  // Asset + transform caches keyed by renderer-assigned object id.
  const assetsRef = useRef<Map<number, AssetEntry>>(new Map());
  // FIFO queue of bytes/sha for incoming objects (matched on the next
  // editor-objects message that surfaces a new id with the same name).
  const pendingAssetsRef = useRef<
    Array<{ name: string; originalName: string; bytes: ArrayBuffer; sha256: string; size: number }>
  >([]);
  const transformsRef = useRef<TransformCache>({});
  // Set of ids seen previously — used to spot newly-added ids per
  // editor-objects broadcast.
  const knownIdsRef = useRef<Set<number>>(new Set());
  // Suppress dirty marking while hydrating from server / IDB.
  const suppressDirtyRef = useRef(false);
  const markDirty = useCallback(() => {
    if (!suppressDirtyRef.current) setDirty(true);
  }, []);

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
        const next = (e.data.objects as SceneObject[]) ?? [];
        // Detect new ids → claim pending asset bytes by name (FIFO).
        const known = knownIdsRef.current;
        const seen = new Set<number>();
        let mutated = false;
        for (const o of next) {
          seen.add(o.id);
          if (!known.has(o.id)) {
            mutated = true;
            const pending = pendingAssetsRef.current;
            const idx = pending.findIndex((p) => p.name === o.name);
            if (idx >= 0) {
              const claim = pending.splice(idx, 1)[0];
              assetsRef.current.set(o.id, {
                name: claim.name,
                filename: claim.originalName,
                size: claim.size,
                bytes: claim.bytes,
                sha256: claim.sha256,
              });
            } else if (!assetsRef.current.has(o.id)) {
              assetsRef.current.set(o.id, { name: o.name, filename: o.name, size: 0 });
            }
            // Pop the matching loading placeholder so its spinner goes
            // away as soon as the engine surfaces the new object.
            setLoadingPlaceholders((prev) => {
              const i = prev.findIndex((p) => p.name === o.name);
              if (i < 0) return prev;
              const next = prev.slice();
              next.splice(i, 1);
              return next;
            });
          } else {
            // Existing object — keep rename in sync.
            const a = assetsRef.current.get(o.id);
            if (a && a.name !== o.name) {
              a.name = o.name;
              mutated = true;
            }
          }
        }
        // Drop assets/transforms for removed ids.
        for (const id of known) {
          if (!seen.has(id)) {
            assetsRef.current.delete(id);
            delete transformsRef.current[id];
            mutated = true;
          }
        }
        knownIdsRef.current = seen;
        setObjects(next);
        if (mutated) markDirty();
      } else if (t === "editor-selection-changed") {
        const nextId = Number(e.data.id) || 0;
        setSelectedId(nextId);
        if (nextId !== 0) setCameraSelected(false);
      } else if (t === "editor-transform") {
        const m = e.data as TransformMsg;
        setTransform(m);
        // Cache the latest transform on every message so Save sees a
        // value even if the user never finalised a drag.
        transformsRef.current[m.id] = {
          position: m.position,
          rotationDeg: m.rotationDeg,
          scale: m.scale,
        };
        if (m.final) markDirty();
      } else if (t === "editor-camera-pose") {
        const pos = e.data.position as Vec3Tuple;
        const fwd = e.data.forward as Vec3Tuple;
        setCameraPose({ position: pos, forward: fwd });
        const last = lastSavedCameraRef.current;
        if (!suppressDirtyRef.current && last) {
          const d =
            Math.abs(last.position[0] - pos[0]) +
            Math.abs(last.position[1] - pos[1]) +
            Math.abs(last.position[2] - pos[2]) +
            Math.abs(last.forward[0] - fwd[0]) +
            Math.abs(last.forward[1] - fwd[1]) +
            Math.abs(last.forward[2] - fwd[2]);
          if (d > 0.001) markDirty();
        } else if (!last) {
          // Capture the initial pose as the save baseline on first emit.
          lastSavedCameraRef.current = { position: pos, forward: fwd };
        }
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
        const ours = bytes.slice(0);
        const sha = await sha256Hex(ours);
        // C++ side strips path + extension when assigning object.name,
        // so push the stripped basename so the FIFO claim-by-name later
        // actually matches. Keep file.name on the asset entry only via
        // sha (used for S3 key), and the extension is recovered by extOf.
        const stem = file.name.replace(/^.*[\\/]/, "").replace(/\.[^.]+$/, "");
        pendingAssetsRef.current.push({
          name: stem,
          originalName: file.name,
          bytes: ours,
          sha256: sha,
          size: file.size,
        });
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

  // --- Save / Load -----------------------------------------------------------

  const buildManifest = useCallback((): SceneManifest => {
    const out: ManifestObject[] = [];
    for (const o of objects) {
      const a = assetsRef.current.get(o.id);
      const tr = transformsRef.current[o.id];
      const kind: ManifestObject["kind"] = (o.kind as ManifestObject["kind"]) ?? "splat";
      const transform = tr
        ? {
            position: tr.position,
            rotation: eulerDegToQuat(tr.rotationDeg),
            scale: tr.scale,
          }
        : {
            position: [0, 0, 0] as Vec3Tuple,
            rotation: [0, 0, 0, 1] as [number, number, number, number],
            scale: [1, 1, 1] as Vec3Tuple,
          };
      const isLight = kind === "light_directional";
      const asset: ManifestAsset | undefined =
        !isLight && a && a.url && a.sha256
          ? { url: a.url, sha256: a.sha256, size: a.size }
          : undefined;
      const light = isLight && o.light ? o.light : undefined;
      const entry: ManifestObject = {
        id: String(o.id),
        kind,
        name: o.name,
        visible: o.visible,
        transform,
      };
      if (asset) entry.asset = asset;
      if (light) entry.light = light;
      out.push(entry);
    }
    // Prepend camera singleton so it lands as the first manifest object.
    const cameraEntry: ManifestObject = {
      id: "camera",
      kind: "camera",
      name: "Camera",
      visible: true,
      transform: {
        position: cameraPose.position,
        rotation: forwardToQuat(cameraPose.forward),
        scale: [1, 1, 1] as Vec3Tuple,
      },
    };
    return { schema: 1, name: sceneName, objects: [cameraEntry, ...out] };
  }, [objects, sceneName, cameraPose]);

  const uploadPendingAssets = useCallback(
    async (effectiveSceneId: string, effectiveUserId: string) => {
      // Upload any object that has bytes but no url yet. SHA-256 dedupes
      // same-content re-uploads (key derived from sha).
      const tasks: Promise<void>[] = [];
      for (const [id, a] of assetsRef.current.entries()) {
        if (a.url || !a.bytes || !a.sha256) continue;
        const ext = extOf(a.filename);
        const key = `${ASSET_KEY_PREFIX}/${effectiveUserId}/${effectiveSceneId}/${a.sha256}.${ext}`;
        const blob = new Blob([a.bytes], { type: "application/octet-stream" });
        const file = new File([blob], a.filename, { type: "application/octet-stream" });
        tasks.push(
          uploadToS3(file, ASSET_BUCKET, key).then((res) => {
            const cur = assetsRef.current.get(id);
            if (cur) {
              cur.url = res.url;
              cur.bytes = undefined; // free memory once uploaded
            }
          }),
        );
      }
      await Promise.all(tasks);
    },
    [],
  );

  // Hydrate the editor from a manifest. Loads bytes from each asset URL
  // (or from a pre-fetched bytes map for the IDB restore case), posts
  // editor-load-* messages, then editor-set-transform.
  const hydrateFromManifest = useCallback(
    async (
      manifest: SceneManifest,
      preloadedBytes?: SceneBytesMap,
    ): Promise<void> => {
      suppressDirtyRef.current = true;
      // Apply camera pose first so the user sees the right viewpoint
      // while assets are still streaming in.
      const camObj = manifest.objects.find((o) => o.kind === "camera");
      if (camObj) {
        const fwd = quatToForward(camObj.transform.rotation);
        const pos = camObj.transform.position;
        setCameraPose({ position: pos, forward: fwd });
        lastSavedCameraRef.current = { position: pos, forward: fwd };
        postToIframe({ type: "editor-set-camera-pose", position: pos, forward: fwd });
      }
      // Show ghost rows + viewport pill for every asset we're about to fetch.
      setLoadingPlaceholders(
        manifest.objects
          .filter((o) => o.kind === "splat" || o.kind === "mesh")
          .map((o) => ({ name: o.name, kind: o.kind })),
      );
      try {
        for (const o of manifest.objects) {
          if (o.kind === "splat" || o.kind === "mesh") {
            let bytes: ArrayBuffer | undefined = preloadedBytes?.[o.id];
            if (!bytes && o.asset?.url) {
              const r = await fetch(o.asset.url);
              if (!r.ok) throw new Error(`Asset fetch failed: ${o.asset.url}`);
              bytes = await r.arrayBuffer();
            }
            if (!bytes) {
              // Couldn't fetch — remove its placeholder so the user isn't
              // stuck staring at a never-resolving spinner.
              setLoadingPlaceholders((prev) => {
                const idx = prev.findIndex((p) => p.name === o.name);
                if (idx < 0) return prev;
                const next = prev.slice();
                next.splice(idx, 1);
                return next;
              });
              continue;
            }
            // Queue the asset so the editor-objects handler links the
            // upcoming new id to its bytes/sha/url (so we don't re-upload).
            const sha = o.asset?.sha256 ?? (await sha256Hex(bytes));
            // Recover filename (with ext) from asset URL when possible.
            const fn = o.asset?.url
              ? o.asset.url.split("/").pop() ?? `${o.name}.splat`
              : `${o.name}.${o.kind === "mesh" ? "glb" : "splat"}`;
            pendingAssetsRef.current.push({
              name: o.name,
              originalName: fn,
              bytes: bytes.slice(0),
              sha256: sha,
              size: o.asset?.size ?? bytes.byteLength,
            });
            const msgType = o.kind === "splat" ? "editor-load-splat" : "editor-load-mesh";
            postToIframe({ type: msgType, bytes, name: o.name }, [bytes]);
          } else if (o.kind === "light_directional") {
            postToIframe({ type: "editor-add-light", name: o.name });
            if (o.light) {
              postToIframe({
                type: "editor-set-light-props",
                color: o.light.color,
                intensity: o.light.intensity,
              });
            }
          }
        }
        // Apply transforms after a tick so the renderer has finished
        // loading and assigned ids. Match by name (FIFO) since we don't
        // have an explicit confirmation message.
        await new Promise((r) => setTimeout(r, 50));
        // Pair manifest objects to the corresponding new object ids by
        // name. Read from assetsRef (mutated synchronously by the
        // editor-objects handler) — React state may not have rendered yet.
        const nameToIds: Record<string, number[]> = {};
        for (const [id, a] of assetsRef.current.entries()) {
          (nameToIds[a.name] = nameToIds[a.name] ?? []).push(id);
        }
        // Skip applying transforms that are exactly identity — those usually
        // come from legacy saves (before lift-to-floor) or buggy first saves.
        // Letting the C++ default lift stick puts the object on the grid
        // instead of stranding it in the raw-splat coordinate frame.
        const isIdentityTransform = (t: ManifestObject["transform"]): boolean => {
          const pZero = t.position.every((v) => Math.abs(v) < 1e-3);
          const sOne = t.scale.every((v) => Math.abs(v - 1) < 1e-3);
          const rIdentity =
            Math.abs(t.rotation[0]) < 1e-3 &&
            Math.abs(t.rotation[1]) < 1e-3 &&
            Math.abs(t.rotation[2]) < 1e-3 &&
            Math.abs(t.rotation[3] - 1) < 1e-3;
          return pZero && sOne && rIdentity;
        };
        for (const o of manifest.objects) {
          const ids = nameToIds[o.name];
          if (!ids || ids.length === 0) continue;
          const id = ids.shift()!;
          if (o.asset?.url) {
            const cur = assetsRef.current.get(id);
            if (cur) cur.url = o.asset.url;
          }
          if (!isIdentityTransform(o.transform)) {
            const eulerDeg = quatToEulerDeg(o.transform.rotation);
            postToIframe({
              type: "editor-set-transform",
              id,
              position: o.transform.position,
              rotationDeg: eulerDeg,
              scale: o.transform.scale,
            });
          }
          if (!o.visible) {
            postToIframe({ type: "editor-set-visibility", id, visible: false });
          }
        }
      } finally {
        // Allow any trailing message bursts to settle before re-enabling
        // dirty tracking — otherwise hydrate-time editor-objects flips
        // dirty=true on its own.
        setTimeout(() => {
          suppressDirtyRef.current = false;
          setDirty(false);
        }, 100);
      }
    },
    [postToIframe],
  );

  const doSave = useCallback(async () => {
    if (saving) return;
    if (!user) {
      // Stash the current state in IDB then bounce through auth.
      const manifest = buildManifest();
      const bytes: SceneBytesMap = {};
      for (const [id, a] of assetsRef.current.entries()) {
        if (a.bytes) bytes[String(id)] = a.bytes;
      }
      try {
        await saveRestorePayload({ manifest, bytes });
      } catch (err) {
        toast.error("Couldn't stash scene for sign-in");
        return;
      }
      navigate("/auth?redirect=/editor?restore=1");
      return;
    }
    setSaving(true);
    try {
      // Allocate the scene id up front so S3 keys can include it. Round
      // trips through the backend so we get a real UUID.
      let id = sceneId;
      if (!id) {
        const created = await editorScenesApi.create({
          name: sceneName,
          manifest: buildManifest(),
        });
        id = created.id;
        setSceneId(id);
        setSearchParams(
          (prev) => {
            const next = new URLSearchParams(prev);
            next.set("scene", id!);
            return next;
          },
          { replace: true },
        );
      }
      await uploadPendingAssets(id, user.id);
      const finalManifest = buildManifest();
      await editorScenesApi.update(id, { name: sceneName, manifest: finalManifest });
      setDirty(false);
      lastSavedCameraRef.current = {
        position: cameraPose.position,
        forward: cameraPose.forward,
      };
      toast.success("Scene saved");
      // Refresh dropdown list so the new/updated scene surfaces immediately.
      editorScenesApi.list().then((r) => setSceneList(r.scenes)).catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Save failed";
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  }, [
    saving,
    user,
    sceneId,
    sceneName,
    cameraPose,
    buildManifest,
    uploadPendingAssets,
    navigate,
    setSearchParams,
  ]);

  // Fetch user's scenes once we know they're logged in. Drives both the
  // Load dropdown and the auto-load-latest behaviour.
  useEffect(() => {
    if (!user) {
      setSceneList([]);
      autoLoadHandledRef.current = false;
      return;
    }
    let cancelled = false;
    editorScenesApi
      .list()
      .then((r) => {
        if (!cancelled) setSceneList(r.scenes);
      })
      .catch(() => {
        /* non-fatal */
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  // Auto-load the most recently-updated scene when the user lands on
  // /editor with no scene or restore param. Runs once per user session.
  useEffect(() => {
    if (autoLoadHandledRef.current) return;
    if (!user) return;
    if (searchParams.get("scene") || searchParams.get("restore") === "1") {
      autoLoadHandledRef.current = true;
      return;
    }
    if (sceneList.length === 0) return; // no scenes yet — stay blank.
    autoLoadHandledRef.current = true;
    const latest = sceneList[0]; // server returns updated_at desc.
    const next = new URLSearchParams();
    next.set("scene", latest.id);
    setSearchParams(next, { replace: true });
  }, [user, sceneList, searchParams, setSearchParams]);

  // URL-driven scene load: ?scene=<uuid>.
  useEffect(() => {
    const id = searchParams.get("scene");
    const restore = searchParams.get("restore");
    if (restore === "1") return; // handled by separate effect.
    if (!id || !rendererReady) return;
    if (id === sceneId) return;
    let cancelled = false;
    (async () => {
      try {
        const scene = await editorScenesApi.get(id);
        if (cancelled) return;
        setSceneId(scene.id);
        setSceneName(scene.name);
        setNameDraft(scene.name);
        await hydrateFromManifest(scene.manifest);
      } catch (err) {
        if (cancelled) return;
        const status = err instanceof ApiError ? err.status : 0;
        if (status === 403 || status === 404) {
          toast.error("Scene not found");
        } else {
          toast.error("Failed to load scene");
        }
        navigate("/editor", { replace: true });
      }
    })();
    return () => {
      cancelled = true;
    };
    // sceneId intentionally not in deps — we only auto-load when URL
    // changes or renderer becomes ready.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, rendererReady]);

  // IDB restore after sign-in detour: ?restore=1.
  useEffect(() => {
    if (searchParams.get("restore") !== "1") return;
    if (!rendererReady) return;
    let cancelled = false;
    (async () => {
      try {
        const payload = await loadRestorePayload();
        if (!payload) {
          // Nothing to restore — clean URL and bail.
          setSearchParams(new URLSearchParams(), { replace: true });
          return;
        }
        setSceneName(payload.manifest.name);
        setNameDraft(payload.manifest.name);
        await hydrateFromManifest(payload.manifest, payload.bytes);
        await clearRestorePayload();
        if (cancelled) return;
        // Re-enable dirty so the auto-save fires (hydrate cleared it).
        setDirty(true);
        await doSave();
        // Strip ?restore=1 (sceneId param is set by doSave).
        setSearchParams(
          (prev) => {
            const next = new URLSearchParams(prev);
            next.delete("restore");
            return next;
          },
          { replace: true },
        );
      } catch (err) {
        toast.error("Couldn't restore scene");
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rendererReady]);

  // onbeforeunload warning while dirty.
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const commitSceneName = useCallback(() => {
    const next = nameDraft.trim() || "Untitled";
    if (next !== sceneName) {
      setSceneName(next);
      markDirty();
    }
    setEditingName(false);
  }, [nameDraft, sceneName, markDirty]);

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
        {loadingPlaceholders.length > 0 && (
          <div className="absolute top-3 right-3 z-20 pointer-events-none">
            <div className="rounded-full border border-border bg-background/85 backdrop-blur px-3 py-1 flex items-center gap-1.5 shadow-md">
              <Loader2 className="h-3 w-3 animate-spin text-primary" />
              <span className="text-[11px] text-foreground/90 tabular-nums">
                Loading {loadingPlaceholders.length} asset
                {loadingPlaceholders.length > 1 ? "s" : ""}…
              </span>
            </div>
          </div>
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
          <SceneHeader
            name={sceneName}
            editing={editingName}
            nameDraft={nameDraft}
            setNameDraft={setNameDraft}
            startEdit={() => {
              setNameDraft(sceneName);
              setEditingName(true);
              requestAnimationFrame(() => nameInputRef.current?.select());
            }}
            commit={commitSceneName}
            cancel={() => setEditingName(false)}
            inputRef={nameInputRef}
            objectCount={objects.length}
            dirty={dirty}
            saving={saving}
            onSave={() => void doSave()}
            scenes={sceneList}
            currentSceneId={sceneId}
            onLoad={(id) => {
              if (id === sceneId) return;
              if (dirty && !window.confirm("Unsaved changes will be lost. Switch scene?")) return;
              const next = new URLSearchParams();
              next.set("scene", id);
              setSearchParams(next, { replace: false });
            }}
            onNewScene={() => {
              if (dirty && !window.confirm("Unsaved changes will be lost. Start a new scene?")) return;
              // Reset everything in-place, then clean URL. Marking autoLoad
              // as handled prevents the auto-load effect from immediately
              // bouncing us back to the latest scene.
              autoLoadHandledRef.current = true;
              postToIframe({ type: "editor-clear-scene" });
              assetsRef.current.clear();
              pendingAssetsRef.current = [];
              transformsRef.current = {};
              knownIdsRef.current = new Set();
              setObjects([]);
              setSelectedId(0);
              setTransform(null);
              setLoadingPlaceholders([]);
              setCameraSelected(false);
              lastSavedCameraRef.current = null;
              setSceneId(null);
              setSceneName("Untitled");
              setNameDraft("Untitled");
              setDirty(false);
              setSearchParams(new URLSearchParams(), { replace: true });
            }}
          />
          <div className="overflow-y-auto max-h-[55vh] border-b border-border/60">
            {objects.length === 0 && loadingPlaceholders.length === 0 && (
              <div className="px-3 py-3 text-[11px] text-muted-foreground/80">
                No objects. Drop a .splat file anywhere, or click + below.
              </div>
            )}
            {/* Camera singleton — always at the top, never deletable. */}
            <div
              onClick={() => {
                setCameraSelected(true);
                postToIframe({ type: "editor-select-object", id: 0 });
              }}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1 cursor-pointer text-[11px] leading-tight",
                "hover:bg-muted/40",
                cameraSelected && "bg-primary/20 text-foreground",
              )}
            >
              <span className="text-muted-foreground/80 inline-flex h-3 w-3 items-center justify-center">
                {/* tiny camera glyph */}
                <svg viewBox="0 0 16 16" className="h-3 w-3" fill="currentColor">
                  <path d="M2 4h3l1-1h4l1 1h3v8H2z" stroke="currentColor" strokeWidth="1" fill="none"/>
                  <circle cx="8" cy="8.5" r="2" stroke="currentColor" strokeWidth="1" fill="none"/>
                </svg>
              </span>
              <span className="flex-1 min-w-0 truncate">Camera</span>
            </div>
            {loadingPlaceholders.map((p, i) => (
              <div
                key={`ghost-${i}-${p.name}`}
                className="flex items-center gap-1.5 px-3 py-1 text-[11px] leading-tight text-muted-foreground/70 italic"
              >
                <Loader2 className="h-3 w-3 animate-spin shrink-0" />
                <span className="flex-1 min-w-0 truncate">{p.name}</span>
                <span className="text-[10px]">loading…</span>
              </div>
            ))}
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

        {/* Transform section — camera takes priority over splat selection. */}
        {cameraSelected && (
          <div className="flex flex-col min-h-0">
            <SectionHeader title="Camera" />
            <div className="px-3 py-1.5 space-y-1">
              <TransformRow
                label="Position"
                values={cameraPose.position}
                digits={2}
                onCommit={(next) => {
                  setCameraPose((prev) => ({ ...prev, position: next }));
                  postToIframe({
                    type: "editor-set-camera-pose",
                    position: next,
                    forward: cameraPose.forward,
                  });
                }}
              />
              <TransformRow
                label="Forward"
                values={cameraPose.forward}
                digits={3}
                onCommit={(next) => {
                  // Renormalize so degenerate input doesn't kill the camera.
                  const len = Math.hypot(next[0], next[1], next[2]) || 1;
                  const fwd: Vec3Tuple = [next[0] / len, next[1] / len, next[2] / len];
                  setCameraPose((prev) => ({ ...prev, forward: fwd }));
                  postToIframe({
                    type: "editor-set-camera-pose",
                    position: cameraPose.position,
                    forward: fwd,
                  });
                }}
              />
            </div>
          </div>
        )}
        {!cameraSelected && selected && (
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

const SceneHeader = ({
  name,
  editing,
  nameDraft,
  setNameDraft,
  startEdit,
  commit,
  cancel,
  inputRef,
  objectCount,
  dirty,
  saving,
  onSave,
  scenes,
  currentSceneId,
  onLoad,
  onNewScene,
}: {
  name: string;
  editing: boolean;
  nameDraft: string;
  setNameDraft: (v: string) => void;
  startEdit: () => void;
  commit: () => void;
  cancel: () => void;
  inputRef: React.RefObject<HTMLInputElement>;
  objectCount: number;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  scenes: EditorSceneListItem[];
  currentSceneId: string | null;
  onLoad: (id: string) => void;
  onNewScene: () => void;
}) => (
  <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border/60">
    {editing ? (
      <input
        ref={inputRef}
        value={nameDraft}
        onChange={(e) => setNameDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          else if (e.key === "Escape") cancel();
          e.stopPropagation();
        }}
        className="flex-1 min-w-0 bg-transparent border border-primary/60 px-1 py-0 text-[11px] outline-none uppercase tracking-wider font-semibold"
      />
    ) : (
      <h2
        onDoubleClick={startEdit}
        className="flex-1 min-w-0 truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground cursor-text"
        title="Double-click to rename"
      >
        {name}
      </h2>
    )}
    {objectCount > 0 && (
      <span className="text-[10px] text-muted-foreground/70 tabular-nums shrink-0">
        {objectCount}
      </span>
    )}
    <DropdownMenu>
      <DropdownMenuTrigger
        className="shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider border border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/40 outline-none"
        aria-label="Load scene"
        title="Load scene"
      >
        <FolderOpen className="h-3 w-3" />
        <span>Load</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[220px]">
        <DropdownMenuItem onClick={onNewScene} className="cursor-pointer">
          <Plus className="h-3.5 w-3.5 mr-1.5" />
          New scene
        </DropdownMenuItem>
        {scenes.length > 0 && <DropdownMenuSeparator />}
        {scenes.map((s) => {
          const isCurrent = s.id === currentSceneId;
          return (
            <DropdownMenuItem
              key={s.id}
              onClick={() => onLoad(s.id)}
              className="cursor-pointer flex items-center gap-1.5"
            >
              <Check
                className={cn(
                  "h-3 w-3",
                  isCurrent ? "opacity-100 text-primary" : "opacity-0",
                )}
              />
              <span className="flex-1 truncate">{s.name}</span>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
    <button
      type="button"
      onClick={onSave}
      disabled={!dirty || saving}
      className={cn(
        "shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider",
        "border border-border/60",
        !dirty || saving
          ? "text-muted-foreground/50 cursor-not-allowed"
          : "text-foreground hover:bg-primary/20 hover:text-foreground",
      )}
      aria-label="Save scene"
      title={saving ? "Saving…" : dirty ? "Save scene" : "No changes"}
    >
      {saving ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : (
        <Save className="h-3 w-3" />
      )}
      <span>{saving ? "Saving…" : "Save"}</span>
    </button>
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
