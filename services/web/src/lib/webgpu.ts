// WebGPU preflight: check API → adapter → device before booting the WASM
// renderer. Returns adapter info on success so Sentry tags crash reports
// with vendor/architecture.

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

// Inline shapes avoid depending on @webgpu/types for two calls.
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

    // Probe device acquisition so a failure surfaces here, not as a mid-boot WASM trap.
    try {
      const device = await adapter.requestDevice();
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
  // Older Chrome only exposed requestAdapterInfo() (async); we read the
  // synchronous adapter.info getter from the current spec.
  if (adapter.info) return { ...EMPTY_INFO, ...adapter.info };
  return EMPTY_INFO;
}

// Apple gates the WebGPU flag to Safari.app; third-party iOS browsers
// (CriOS/FxiOS/EdgiOS) run on WKWebView and can't see the toggle, so the
// two cases need different remediation copy.
function isIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  if (/iPad|iPhone|iPod/.test(navigator.userAgent)) return true;
  // iPadOS 13+ reports as desktop Safari; touch-points is Apple's recommended check.
  return navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
}

function isIOSSafari(): boolean {
  if (!isIOS() || typeof navigator === "undefined") return false;
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
            title: "WebGPU is not enabled",
            body: "Turn it on in iOS Settings to run the renderer.",
            hint: "Steps:",
            steps: [
              "Open the Settings app",
              "Go to Apps → Safari → Advanced → Feature Flags",
              "Toggle WebGPU on",
              "Reload this page",
            ],
          };
        }
        return {
          title: "WebGPU is not available in this browser",
          body: "On iOS it's only available in Safari.",
          hint: "To enable it:",
          steps: [
            "Open this page in Safari",
            "Open Settings → Apps → Safari → Advanced → Feature Flags",
            "Toggle WebGPU on",
            "Reload the page",
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
