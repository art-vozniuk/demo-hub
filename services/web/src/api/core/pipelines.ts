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

export interface GenerativeEditingResult {
  result_url: string;
}

export type PipelineResult =
  | FaceRecognitionResult
  | FaceSwapResult
  | GenerativeEditingResult
  | Record<string, any>;

export interface PipelineStatusItem {
  id: string;
  pipeline_name: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
  message?: string | null;
  result?: PipelineResult | null;
  eta_seconds?: number | null;
}

export interface PipelineStatusResponse {
  pipelines: PipelineStatusItem[];
}

export const pipelinesApi = {
  queuePipelines: async (
    request: QueuePipelinesRequest
  ): Promise<QueuePipelinesResponse> => {
    return apiClient.post<QueuePipelinesResponse>("/pipelines/queue", request);
  },

  getStatus: async (pipelineIds: string[]): Promise<PipelineStatusResponse> => {
    return apiClient.post<PipelineStatusResponse>("/pipelines/status", {
      pipeline_ids: pipelineIds,
    });
  },
};
