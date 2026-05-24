import { apiClient } from "../client";

export interface PipelineJobInput {
  pipeline_id: string;
  pipeline_name: string;
  input: Record<string, any>;
}

export interface QueuePipelinesRequest {
  trace_id: string;
  jobs: PipelineJobInput[];
}

export interface QueuePipelinesResponse {
  trace_id: string;
  pipeline_ids: string[];
  queue_length: number;
}

export interface DetectedFace {
  id: string;
  bbox: [number, number, number, number];
  det_score: number | null;
}

export interface FaceRecognitionResult {
  image_width: number;
  image_height: number;
  faces: DetectedFace[];
}

export interface FaceSwapResult {
  result_url: string;
}

export interface FluxResult {
  result_url: string;
}

export interface SharpResult {
  result_url: string;
  camera_eye: [number, number, number];
  camera_fwd: [number, number, number];
  gaussian_count?: number;
}

export interface TrellisResult {
  result_url: string;
}

export type PipelineResult =
  | FaceRecognitionResult
  | FaceSwapResult
  | FluxResult
  | SharpResult
  | TrellisResult
  | Record<string, any>;

export interface PipelineStatusItem {
  id: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
  message?: string | null;
  result?: PipelineResult | null;
}

export interface PipelineStatusResponse {
  pipelines: PipelineStatusItem[];
}

export interface PipelineEstimateResponse {
  pipeline_id: string;
  estimated_seconds: number;
  queue_position: number;
  worker_count: number;
  workers_missing: boolean;
}

export type PipelineStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";

export interface UserPipelineItem {
  id: string;
  pipeline_name: string;
  status: PipelineStatus;
  message?: string | null;
  input?: Record<string, any> | null;
  result?: PipelineResult | null;
  created_at: string;
  updated_at: string;
}

export interface UserPipelinesResponse {
  pipelines: UserPipelineItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface PublicPipeline {
  id: string;
  pipeline_name: string;
  status: PipelineStatus;
  input?: Record<string, any> | null;
  result?: PipelineResult | null;
  created_at: string;
}

export interface CostPreviewRequest {
  pipeline_name: string;
  input: Record<string, unknown>;
}

export interface CostPreviewResponse {
  pipeline_name: string;
  base_cost: number;
  cost: number;
}

export const pipelinesApi = {
  queuePipelines: async (
    request: QueuePipelinesRequest,
  ): Promise<QueuePipelinesResponse> => {
    return apiClient.post<QueuePipelinesResponse>(
      "/pipelines/queue",
      request,
    );
  },

  getStatus: async (pipelineIds: string[]): Promise<PipelineStatusResponse> => {
    return apiClient.post<PipelineStatusResponse>("/pipelines/status", {
      pipeline_ids: pipelineIds,
    });
  },

  getEstimate: async (
    pipelineId: string
  ): Promise<PipelineEstimateResponse> => {
    return apiClient.get<PipelineEstimateResponse>(
      `/pipelines/${pipelineId}/estimate`
    );
  },

  getMine: async (
    limit = 50,
    offset = 0,
  ): Promise<UserPipelinesResponse> => {
    return apiClient.get<UserPipelinesResponse>(
      `/pipelines/mine?limit=${limit}&offset=${offset}`,
    );
  },

  getPublic: async (pipelineId: string): Promise<PublicPipeline> => {
    return apiClient.get<PublicPipeline>(
      `/pipelines/${pipelineId}/public`,
    );
  },

  previewCost: async (
    request: CostPreviewRequest,
  ): Promise<CostPreviewResponse> => {
    return apiClient.post<CostPreviewResponse>(
      "/pipelines/cost-preview",
      request,
    );
  },
};
