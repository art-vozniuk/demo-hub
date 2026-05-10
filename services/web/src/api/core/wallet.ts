import { apiClient } from "../client";

export interface BalanceResponse {
  tokens: number;
  is_anonymous: boolean;
  // pipeline_name -> base_cost. Source of truth lives in pipeline_types
  // (DB); the frontend never hardcodes prices.
  pipeline_costs: Record<string, number>;
}

export const walletApi = {
  getBalance: async (): Promise<BalanceResponse> => {
    return apiClient.get<BalanceResponse>("/me/balance");
  },
};
