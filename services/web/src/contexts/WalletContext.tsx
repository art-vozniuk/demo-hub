import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react';

import { walletApi, type BalanceResponse, ApiError } from '@/api';
import { useAuth } from '@/contexts/AuthContext';

interface WalletContextType {
  balance: number | null;
  isAnonymous: boolean | null;
  isLoading: boolean;
  // pipeline_name -> base_cost, sourced from the DB via /me/balance.
  costs: Record<string, number> | null;
  getCost: (pipelineName: string) => number | undefined;
  // True when backend requires a Turnstile token for anon /pipelines/queue.
  turnstileRequired: boolean;
  refresh: () => Promise<void>;
}

const WalletContext = createContext<WalletContextType | undefined>(undefined);

export const WalletProvider = ({ children }: { children: ReactNode }) => {
  const { loading: authLoading, user } = useAuth();
  const [balance, setBalance] = useState<number | null>(null);
  const [isAnonymous, setIsAnonymous] = useState<boolean | null>(null);
  const [costs, setCosts] = useState<Record<string, number> | null>(null);
  const [turnstileRequired, setTurnstileRequired] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  // Coalesce concurrent /me/balance calls so StrictMode + auth state
  // churn don't each create their own anon cookie/grant.
  const inFlightRef = useRef<Promise<void> | null>(null);

  const refresh = useCallback((): Promise<void> => {
    if (inFlightRef.current) return inFlightRef.current;
    const promise = (async () => {
      try {
        const resp: BalanceResponse = await walletApi.getBalance();
        setBalance(resp.tokens);
        setIsAnonymous(resp.is_anonymous);
        setCosts(resp.pipeline_costs);
        setTurnstileRequired(resp.turnstile_required);
      } catch (err) {
        if (!(err instanceof ApiError) || err.status !== 401) {
          console.warn('balance refresh failed:', err);
        }
      } finally {
        setIsLoading(false);
        inFlightRef.current = null;
      }
    })();
    inFlightRef.current = promise;
    return promise;
  }, []);

  useEffect(() => {
    if (authLoading) return;
    refresh();
  }, [authLoading, user?.id, refresh]);

  useEffect(() => {
    const onFocus = () => {
      refresh();
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refresh]);

  const getCost = useCallback(
    (pipelineName: string) => costs?.[pipelineName],
    [costs],
  );

  return (
    <WalletContext.Provider
      value={{
        balance,
        isAnonymous,
        isLoading,
        costs,
        getCost,
        turnstileRequired,
        refresh,
      }}
    >
      {children}
    </WalletContext.Provider>
  );
};

export const useWallet = () => {
  const ctx = useContext(WalletContext);
  if (ctx === undefined) {
    throw new Error('useWallet must be used within a WalletProvider');
  }
  return ctx;
};
