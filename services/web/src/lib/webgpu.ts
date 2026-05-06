/**
 * WebGPU pre-flight: tells us up-front whether the user can run the renderer
 * at all, *before* we boot a 30 MB WASM module that's just going to assert
 * and trap. Three failure modes worth distinguishing:
 *
 *   - no-api      → browser doesn't expose `navigator.gpu`. iOS <18, older
 *                   Android Chrome, Firefox without flag, etc. Most common.
 *   - no-adapter  → API exists but `requestAdapter()` returned null. Means
 *                   the device has no WebGPU-compatible GPU surfaced (some
 *                   integrated GPUs on Linux, some virtualised desktops).
 *   - no-device   → adapter granted but `requestDevice()` threw. Rare; usually
 *                   means the adapter doesn't satisfy minimum limits.
 *
 * We return adapter info on success so Sentry can tag every later report with
 * vendor/architecture — letting us slice crash rate by GPU class.
 */

export interface AdapterInfo {
  vendor: string;
  architecture: string;
  device: string;
  description: string;
}

export type WebGpuStatus =
  | { kind: "supported";    adapterInfo: AdapterInfo }
  | { kind: "no-api" }
  | { kind: "no-adapter" }
  | { kind: "no-device";    reason: string };

const EMPTY_INFO: AdapterInfo = {
  vendor: "", architecture: "", device: "", description: "",
};

// Narrow inline shapes — avoids depending on @webgpu/types just for two calls.
interface MinimalAdapter {
  info?: Partial<AdapterInfo>;
  requestDevice: () => Promise<{ destroy?: () => void }>;
  requestAdapterInfo?: () => Promise<Partial<AdapterInfo>>;
}
interface MinimalGpu {
  requestAdapter: () => Promise<MinimalAdapter | null>;
}

export async function checkWebGpu(): Promise<WebGpuStatus> {
  if (typeof navigator === "undefined" || !("gpu" in navigator)) {
    return { kind: "no-api" };
  }
  const gpu = (navigator as Navigator & { gpu?: MinimalGpu }).gpu;
  if (!gpu) return { kind: "no-api" };

  try {
    const adapter = await gpu.requestAdapter();
    if (!adapter) return { kind: "no-adapter" };

    // Try to grab a device too — same as the renderer will do moments later.
    // If it fails here, we get a clean error instead of a mid-boot WASM trap.
    try {
      const device = await adapter.requestDevice();
      // Drop it immediately — we just wanted to confirm it's grantable.
      device.destroy?.();
    } catch (err) {
      return {
        kind: "no-device",
        reason: err instanceof Error ? err.message : String(err),
      };
    }

    return { kind: "supported", adapterInfo: extractAdapterInfo(adapter) };
  } catch (err) {
    return {
      kind: "no-device",
      reason: err instanceof Error ? err.message : String(err),
    };
  }
}

function extractAdapterInfo(adapter: MinimalAdapter): AdapterInfo {
  // New spec: adapter.info is a plain getter. Older Chrome only had
  // requestAdapterInfo() (async); we can only return the new shape here.
  if (adapter.info) return { ...EMPTY_INFO, ...adapter.info };
  return EMPTY_INFO;
}

// All iOS browsers are forced to use WebKit, but Apple gates the WebGPU
// feature flag to Safari.app — third-party iOS browsers (Chrome via CriOS,
// Firefox via FxiOS, Edge via EdgiOS) sit on WKWebView and don't get the
// toggle. So we have to tell the two cases apart and give different advice.
function isIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  if (/iPad|iPhone|iPod/.test(navigator.userAgent)) return true;
  // iPadOS 13+ reports as desktop Safari; the touch-points heuristic is
  // Apple's own recommended workaround.
  return navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
}

function isIOSSafari(): boolean {
  if (!isIOS() || typeof navigator === "undefined") return false;
  // Any of these tokens means we're inside a non-Safari WKWebView wrapper.
  // Keep the list narrow on purpose: future browsers without their own
  // token would (correctly) fall through to the Safari branch.
  if (/CriOS|FxiOS|EdgiOS|OPiOS|YaBrowser|DuckDuckGo|GSA/.test(navigator.userAgent)) {
    return false;
  }
  return /Safari\//.test(navigator.userAgent);
}

/** Friendly user-facing description of why the renderer can't start. */
export function describeUnsupported(status: WebGpuStatus): {
  title: string;
  body:  string;
  hint:  string;
  steps?: string[];
} {
  switch (status.kind) {
    case "no-api":
      if (isIOS()) {
        if (isIOSSafari()) {
          return {
            title: "WebGPU isn't enabled in Safari yet",
            body:
              "iOS 18 ships WebGPU, but it's behind a Safari feature flag that's " +
              "off by default. Flip it once and the renderer will work.",
            hint: "Turn on the WebGPU feature flag in iOS Settings, then reload this page:",
            steps: [
              "Open the Settings app on your iPhone or iPad",
              "Go to Apps → Safari → Advanced → Feature Flags (on iOS 17 or earlier: Settings → Safari → Advanced → Feature Flags)",
              "Toggle WebGPU on",
              "Come back to this tab and reload the page",
            ],
          };
        }
        return {
          title: "WebGPU isn't available in this iOS browser",
          body:
            "On iPhone and iPad, only Safari can run WebGPU. Chrome, Firefox, Edge " +
            "and other iOS browsers all share Apple's WebKit engine, but Apple gates " +
            "the WebGPU feature flag to Safari itself — so it can't be enabled here.",
          hint: "Open this page in Safari, then turn on the WebGPU flag:",
          steps: [
            "Copy this page's URL and open it in Safari",
            "In iOS Settings: Apps → Safari → Advanced → Feature Flags (on iOS 17 or earlier: Settings → Safari → Advanced → Feature Flags)",
            "Toggle WebGPU on",
            "Reload the page in Safari",
          ],
        };
      }
      return {
        title: "Your browser doesn't support WebGPU",
        body:
          "The renderer needs WebGPU — a graphics API that's not yet available " +
          "in this browser.",
        hint:
          "On desktop, use the latest Chrome, Edge, or Safari 18+. " +
          "On Android, use Chrome 121+ (some devices still need to enable the flag chrome://flags/#enable-unsafe-webgpu).",
      };
    case "no-adapter":
      return {
        title: "No WebGPU-compatible GPU found",
        body:
          "Your browser supports WebGPU, but it couldn't find a GPU it can " +
          "talk to. This sometimes happens on virtual machines or older " +
          "integrated graphics.",
        hint: "Try opening this page on a different device.",
      };
    case "no-device":
      return {
        title: "WebGPU is unavailable on this device",
        body:
          "Your GPU was detected but couldn't satisfy the renderer's minimum " +
          "requirements.",
        hint:
          status.reason
            ? `Technical detail: ${status.reason}`
            : "Updating your browser or graphics driver may help.",
      };
    default:
      return {
        title: "WebGPU check passed",
        body: "",
        hint: "",
      };
  }
}
