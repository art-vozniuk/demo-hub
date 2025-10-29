import { createContext, useContext, useEffect, ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { initGA, trackPageView } from '@/lib/analytics';

const AnalyticsContext = createContext<null>(null);

export const AnalyticsProvider = ({ children }: { children: ReactNode }) => {
  const location = useLocation();

  useEffect(() => {
    initGA();
  }, []);

  useEffect(() => {
    const pageTitles: Record<string, string> = {
      '/': 'Home',
      '/face-fusion': 'Face Fusion - Templates',
      '/face-fusion/generate': 'Face Fusion - Generate',
      '/auth': 'Authentication',
    };

    const title = pageTitles[location.pathname] || 'Page';
    trackPageView(location.pathname, title);
  }, [location]);

  return <AnalyticsContext.Provider value={null}>{children}</AnalyticsContext.Provider>;
};

export const useAnalyticsContext = () => useContext(AnalyticsContext);

