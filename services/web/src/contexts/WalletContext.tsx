import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react';

import {
  walletApi,
  type BalanceResponse,
  type CostMultiplierRule,
  ApiError,
} from '@/api';
import { useAuth } from '@/contexts/AuthContext';

interface WalletContextType {
  balance: number | null;
  isLoading: boolean;
  // pipeline_name -> base_cost, sourced from the DB via /me/balance.
  costs: Record<string, number> | null;
  getCost: (pipelineName: string) => number | undefined;
  // Final cost preview given the input the user is about to send.
  // Mirrors services/core/app/pipelines/cost_resolution.py — server
  // remains authoritative at charge time.
  resolveCost: (
    pipelineName: string,
    input?: Record<string, unknown>,
  ) => number | undefined;
  // pipeline_name -> rule, sourced from /me/balance. Only contains
  // entries for pipelines whose cost varies with input.
  costMultipliers: Record<string, CostMultiplierRule> | null;
  // One-time signup grant, sourced from core via /me/balance. Null until
  // the first balance fetch resolves.
  signupGrant: number | null;
  refresh: () => Promise<void>;
}

const WalletContext = createContext<WalletContextType | undefined>(undefined);

export const WalletProvider = ({ children }: { children: ReactNode }) => {
  const { loading: authLoading, user } = useAuth();
  const [balance, setBalance] = useState<number | null>(null);
  const [costs, setCosts] = useState<Record<string, number> | null>(null);
  const [costMultipliers, setCostMultipliers] = useState<Record<
    string,
    CostMultiplierRule
  > | null>(null);
  const [signupGrant, setSignupGrant] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  // Coalesce concurrent /me/balance calls so StrictMode + auth state
  // churn don't each fire their own request.
  const inFlightRef = useRef<Promise<void> | null>(null);

  const refresh = useCallback((): Promise<void> => {
    if (inFlightRef.current) return inFlightRef.current;
    const promise = (async () => {
      try {
        const resp: BalanceResponse = await walletApi.getBalance();
        setBalance(resp.tokens);
        setCosts(resp.pipeline_costs);
        setCostMultipliers(resp.pipeline_cost_multipliers ?? {});
        setSignupGrant(resp.signup_grant);
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

  const resolveCost = useCallback(
    (pipelineName: string, input?: Record<string, unknown>) => {
      const base = costs?.[pipelineName];
      if (base === undefined) return undefined;
      const rule = costMultipliers?.[pipelineName];
      if (!rule || !input) return base;
      const raw = input[rule.input_field];
      if (raw === undefined || raw === null) return base;
      const pct = rule.values[String(raw)];
      if (pct === undefined) return base;
      return Math.max(0, Math.floor((base * pct) / 100));
    },
    [costs, costMultipliers],
  );

  return (
    <WalletContext.Provider
      value={{
        balance,
        isLoading,
        costs,
        getCost,
        resolveCost,
        costMultipliers,
        signupGrant,
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
