import { useCallback } from 'react';
import { trackEvent } from '@/lib/analytics';
import type { AnalyticsEvent } from '@/types/analytics';

export const useAnalytics = () => {
  const track = useCallback((event: AnalyticsEvent) => {
    trackEvent(event);
  }, []);

  return { track };
};

