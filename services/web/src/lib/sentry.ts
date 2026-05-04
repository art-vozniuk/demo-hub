import * as Sentry from "@sentry/react";

import type { WebGpuStatus } from "./webgpu";

const DSN     = import.meta.env.VITE_SENTRY_DSN     as string | undefined;
const ENV     = import.meta.env.VITE_SENTRY_ENV     as string | undefined;
const RELEASE = import.meta.env.VITE_BUILD_TAG      as string | undefined;

let initialized = false;

export function initSentry(): void {
  if (initialized) return;
  if (!DSN) {
    // Soft-disable when DSN isn't provided so local dev doesn't shout.
    if (import.meta.env.DEV) {
      console.info("[sentry] VITE_SENTRY_DSN not set — Sentry disabled");
    }
    return;
  }

  Sentry.init({
    dsn: DSN,
    environment: ENV ?? "unknown",
    release: RELEASE,
    integrations: [Sentry.browserTracingIntegration()],
    // Performance: keep low until we know we have headroom in the Sentry quota.
    tracesSampleRate: 0.1,
    // Replay disabled by default — adds bundle weight; opt-in later if needed.
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    sendDefaultPii: true,
  });
  Sentry.setTag("service", "web");
  initialized = true;
}

/** Stamp WebGPU adapter info on the current session for every report. */
export function setWebGpuContext(status: WebGpuStatus): void {
  if (!initialized) return;
  Sentry.setTag("webgpu.kind", status.kind);
  if (status.kind === "supported" && status.adapterInfo) {
    const info = status.adapterInfo;
    Sentry.setTag("webgpu.vendor", info.vendor || "unknown");
    Sentry.setTag("webgpu.architecture", info.architecture || "unknown");
    Sentry.setContext("webgpu", {
      vendor:       info.vendor,
      architecture: info.architecture,
      device:       info.device,
      description:  info.description,
    });
  }
}

/** Capture an engine-side failure with structured context. */
export function captureEngineError(payload: {
  reason: "no-webgpu-api" | "no-adapter" | "abort" | "window-error" | "stall" | "unknown";
  message?: string;
  scene?: { slug: string; title: string } | null;
  engineLogTail?: string[];
}): void {
  if (!initialized) {
    console.warn("[sentry] not initialized — engine error dropped:", payload);
    return;
  }
  Sentry.captureMessage(payload.message ?? `renderer: ${payload.reason}`, {
    level: "error",
    tags: {
      "renderer.failure": payload.reason,
    },
    contexts: {
      renderer: {
        scene_slug:  payload.scene?.slug,
        scene_title: payload.scene?.title,
        engine_log_tail: payload.engineLogTail?.slice(-30).join("\n"),
      },
    },
  });
}

/** Drop a breadcrumb so subsequent errors carry recent UX state. */
export function rendererBreadcrumb(message: string, data?: Record<string, unknown>): void {
  if (!initialized) return;
  Sentry.addBreadcrumb({ category: "renderer", level: "info", message, data });
}

export { Sentry };
