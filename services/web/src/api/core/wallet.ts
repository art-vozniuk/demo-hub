import { apiClient } from "../client";

export interface BalanceResponse {
  // 0 when caller is not authenticated.
  tokens: number;
  // pipeline_name -> base_cost. Source of truth lives in pipeline_types
  // (DB); the frontend never hardcodes prices.
  pipeline_costs: Record<string, number>;
  // One-time grant a user receives on first sign-in. Source of truth lives
  // in services/core/app/wallet/service.py — the frontend never hardcodes it.
  signup_grant: number;
}

export const walletApi = {
  getBalance: async (): Promise<BalanceResponse> => {
    return apiClient.get<BalanceResponse>("/me/balance");
  },
};
