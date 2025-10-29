import type { AnalyticsEvent, GtagConfig } from '@/types/analytics';

const GA_MEASUREMENT_ID = import.meta.env.VITE_GA_MEASUREMENT_ID;
const IS_PRODUCTION = import.meta.env.PROD;
const DEBUG = !IS_PRODUCTION;

declare global {
  interface Window {
    gtag?: (
      command: 'config' | 'event' | 'js',
      targetId: string | Date,
      config?: GtagConfig | Record<string, unknown>
    ) => void;
    dataLayer?: unknown[];
  }
}

export const initGA = (): void => {
  if (!GA_MEASUREMENT_ID) {
    if (DEBUG) console.warn('GA_MEASUREMENT_ID not configured');
    return;
  }

  if (typeof window === 'undefined') return;

  const script1 = document.createElement('script');
  script1.async = true;
  script1.src = `https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`;
  document.head.appendChild(script1);

  const script2 = document.createElement('script');
  script2.innerHTML = `
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', '${GA_MEASUREMENT_ID}', {
      send_page_view: false
    });
  `;
  document.head.appendChild(script2);

  if (DEBUG) console.log('GA4 initialized:', GA_MEASUREMENT_ID);
};

export const trackPageView = (path: string, title?: string): void => {
  if (!GA_MEASUREMENT_ID || !window.gtag) return;

  window.gtag('config', GA_MEASUREMENT_ID, {
    page_path: path,
    page_title: title,
  });

  if (DEBUG) console.log('GA4 Page View:', { path, title });
};

export const trackEvent = <T extends AnalyticsEvent>(event: T): void => {
  if (!GA_MEASUREMENT_ID || !window.gtag) {
    if (DEBUG) console.log('GA4 Event (not sent):', event);
    return;
  }

  window.gtag('event', event.name, event.params);

  if (DEBUG) console.log('GA4 Event:', event);
};

export const setUserId = (userId: string | null): void => {
  if (!GA_MEASUREMENT_ID || !window.gtag) return;

  window.gtag('config', GA_MEASUREMENT_ID, {
    user_id: userId ?? undefined,
  });

  if (DEBUG) console.log('GA4 User ID set:', userId);
};

