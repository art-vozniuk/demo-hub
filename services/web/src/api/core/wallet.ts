import { apiClient } from "../client";

export interface CostMultiplierRule {
  input_field: string;
  // input value (stringified) -> percent of base_cost (100 = 1x)
  values: Record<string, number>;
}

export interface BalanceResponse {
  // 0 when caller is not authenticated.
  tokens: number;
  // pipeline_name -> base_cost. Source of truth lives in pipeline_types
  // (DB); the frontend never hardcodes prices.
  pipeline_costs: Record<string, number>;
  // pipeline_name -> optional input-driven multiplier rule. Mirrored
  // here so the UI can preview the final price live as the user toggles
  // params; backend re-resolves authoritatively at charge time.
  pipeline_cost_multipliers: Record<string, CostMultiplierRule>;
  // One-time grant a user receives on first sign-in. Source of truth lives
  // in services/core/app/wallet/service.py — the frontend never hardcodes it.
  signup_grant: number;
}

export const walletApi = {
  getBalance: async (): Promise<BalanceResponse> => {
    return apiClient.get<BalanceResponse>("/me/balance");
  },
};
