import { apiClient } from "../client";

export interface BalanceResponse {
  // 0 when caller is not authenticated.
  tokens: number;
  // pipeline_name -> base_cost. Variable-priced pipelines must hit
  // POST /pipelines/cost-preview for the input-aware final cost.
  pipeline_costs: Record<string, number>;
  // One-time grant a user receives on first sign-in.
  signup_grant: number;
}

export const walletApi = {
  getBalance: async (): Promise<BalanceResponse> => {
    return apiClient.get<BalanceResponse>("/me/balance");
  },
};
