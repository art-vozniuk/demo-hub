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

// Invisible Turnstile widget; getToken() resolves a fresh challenge.
// Returns null tokens when disabled or VITE_TURNSTILE_SITE_KEY is unset.
export function useTurnstile(enabled: boolean = true) {
  const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY as string | undefined;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const pendingResolve = useRef<((token: string) => void) | null>(null);
  const pendingReject = useRef<((err: Error) => void) | null>(null);
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
            pendingReject.current = null;
            resolve?.(token);
          },
          'error-callback': () => {
            const reject = pendingReject.current;
            pendingResolve.current = null;
            pendingReject.current = null;
            reject?.(new Error('turnstile error'));
          },
          'expired-callback': () => {
            // Harmless: next execute() mints a fresh token.
          },
        });
        setIsReady(true);
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
      setIsReady(false);
    };
  }, [enabled, siteKey]);

  const getToken = useCallback((): Promise<string | null> => {
    if (!enabled || !siteKey) return Promise.resolve(null);
    if (!isReady || !widgetIdRef.current || !window.turnstile) {
      return Promise.resolve(null);
    }

    return new Promise((resolve, reject) => {
      pendingResolve.current = resolve as (token: string) => void;
      pendingReject.current = reject;
      try {
        window.turnstile!.reset(widgetIdRef.current!);
        window.turnstile!.execute(widgetIdRef.current!);
      } catch (err) {
        pendingResolve.current = null;
        pendingReject.current = null;
        reject(err as Error);
      }
    });
  }, [enabled, siteKey, isReady]);

  return { getToken, isReady };
}
