import { useCallback, useEffect, useRef, useState } from 'react';

const SCRIPT_SRC =
  'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: HTMLElement | string,
        options: {
          sitekey: string;
          size?: 'normal' | 'compact' | 'invisible';
          callback?: (token: string) => void;
          'error-callback'?: () => void;
          'expired-callback'?: () => void;
        },
      ) => string;
      reset: (widgetId?: string) => void;
      execute: (widgetId?: string) => void;
      remove: (widgetId?: string) => void;
    };
  }
}

let scriptPromise: Promise<void> | null = null;

const loadScript = (): Promise<void> => {
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    if (window.turnstile) {
      resolve();
      return;
    }
    const existing = document.querySelector(`script[src="${SCRIPT_SRC}"]`);
    if (existing) {
      existing.addEventListener('load', () => resolve());
      existing.addEventListener('error', () => reject(new Error('turnstile script failed')));
      return;
    }
    const script = document.createElement('script');
    script.src = SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('turnstile script failed'));
    document.head.appendChild(script);
  });
  return scriptPromise;
};

const READY_WAIT_MS = 10_000;
const EXECUTE_TIMEOUT_MS = 15_000;

// Invisible Turnstile widget; getToken() resolves a fresh challenge.
// Returns null tokens when disabled or VITE_TURNSTILE_SITE_KEY is unset,
// or when the widget fails to produce a token within the timeout.
export function useTurnstile(enabled: boolean = true) {
  const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY as string | undefined;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const pendingResolve = useRef<((token: string | null) => void) | null>(null);
  const isReadyRef = useRef(false);
  const readyWaitersRef = useRef<Array<() => void>>([]);
  // Serializes concurrent getToken() callers — execute() on a widget that's
  // already running is rejected by Turnstile (and drops the prior pending token).
  const inFlightRef = useRef<Promise<string | null> | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    if (!enabled || !siteKey) {
      return;
    }

    let cancelled = false;
    let container: HTMLDivElement | null = null;

    loadScript()
      .then(() => {
        if (cancelled || !window.turnstile) return;
        container = document.createElement('div');
        container.style.position = 'absolute';
        container.style.left = '-9999px';
        container.style.top = '-9999px';
        document.body.appendChild(container);
        containerRef.current = container;

        widgetIdRef.current = window.turnstile.render(container, {
          sitekey: siteKey,
          size: 'invisible',
          callback: (token: string) => {
            const resolve = pendingResolve.current;
            pendingResolve.current = null;
            resolve?.(token);
          },
          'error-callback': () => {
            const resolve = pendingResolve.current;
            pendingResolve.current = null;
            resolve?.(null);
          },
          'expired-callback': () => {
            // Harmless: next execute() mints a fresh token.
          },
        });
        isReadyRef.current = true;
        setIsReady(true);
        readyWaitersRef.current.forEach((r) => r());
        readyWaitersRef.current = [];
      })
      .catch((err) => {
        console.warn('turnstile load failed:', err);
      });

    return () => {
      cancelled = true;
      if (widgetIdRef.current && window.turnstile) {
        try {
          window.turnstile.remove(widgetIdRef.current);
        } catch {
          // ignore
        }
      }
      widgetIdRef.current = null;
      if (container) {
        container.remove();
        containerRef.current = null;
      }
      isReadyRef.current = false;
      setIsReady(false);
    };
  }, [enabled, siteKey]);

  const getToken = useCallback(async (): Promise<string | null> => {
    if (!enabled || !siteKey) return null;

    // Wait until the widget is mounted, in case the user clicks Generate
    // before the script finished loading. Bounded so we never hang.
    if (!isReadyRef.current) {
      const ready = await new Promise<boolean>((resolve) => {
        const timer = setTimeout(() => resolve(false), READY_WAIT_MS);
        readyWaitersRef.current.push(() => {
          clearTimeout(timer);
          resolve(true);
        });
      });
      if (!ready) return null;
    }

    if (!widgetIdRef.current || !window.turnstile) return null;

    const prior = inFlightRef.current;
    if (prior) await prior.catch(() => null);

    const promise = new Promise<string | null>((resolve) => {
      let timer: ReturnType<typeof setTimeout> | null = null;
      const settle = (token: string | null) => {
        if (timer) clearTimeout(timer);
        pendingResolve.current = null;
        resolve(token);
      };
      pendingResolve.current = settle;
      timer = setTimeout(() => {
        if (pendingResolve.current === settle) settle(null);
      }, EXECUTE_TIMEOUT_MS);
      try {
        window.turnstile!.reset(widgetIdRef.current!);
        window.turnstile!.execute(widgetIdRef.current!);
      } catch (err) {
        console.warn('turnstile execute failed:', err);
        settle(null);
      }
    });
    inFlightRef.current = promise;
    void promise.finally(() => {
      if (inFlightRef.current === promise) inFlightRef.current = null;
    });
    return promise;
  }, [enabled, siteKey]);

  return { getToken, isReady };
}
