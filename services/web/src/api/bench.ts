import { apiClient } from "./client";

export type BenchTier = "MOCK_LOCAL" | "MOCK_MODAL" | "REAL";
export type BenchConfig =
  | "flux_opt_a10g"
  | "flux_opt_h100"
  | "flux_modal_mock"
  | "flux_local_mock";
export type BenchRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "aborted"
  | "failed";

export interface BenchRunCreate {
  config: BenchConfig;
  tier: BenchTier;
  budget_usd: number;
  concurrency: number;
  sample_input: Record<string, unknown>;
}

export interface BenchEstimateRequest {
  config: BenchConfig;
  tier: BenchTier;
  budget_usd: number;
}

export interface BenchEstimateResponse {
  expected_images_low: number;
  expected_images_high: number;
  expected_time_seconds_low: number;
  expected_time_seconds_high: number;
  cold_start_risk_pct: number;
  todays_spend_usd: number;
  daily_cap_usd: number;
  proceedable: boolean;
  reason: string | null;
}

export interface BenchRunSummary {
  run_id: string;
  config: BenchConfig;
  tier: BenchTier;
  status: BenchRunStatus;
  budget_usd: number;
  concurrency: number;
  images_generated: number;
  failures: number;
  cost_usd: number;
  elapsed_seconds: number;
  started_at: string;
  finished_at: string | null;
}

export const benchApi = {
  startRun: (body: BenchRunCreate) =>
    apiClient.post<{ run_id: string; status: BenchRunStatus }, BenchRunCreate>(
      "/bench/runs",
      body,
    ),
  listRuns: () => apiClient.get<{ runs: BenchRunSummary[] }>("/bench/runs"),
  getRun: (runId: string) =>
    apiClient.get<BenchRunSummary>(`/bench/runs/${runId}`),
  estimate: (body: BenchEstimateRequest) =>
    apiClient.post<BenchEstimateResponse, BenchEstimateRequest>(
      "/bench/estimate",
      body,
    ),
};
