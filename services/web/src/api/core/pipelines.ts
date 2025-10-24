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

export interface PipelineStatusItem {
  id: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
  result_url?: string | null;
  message?: string | null;
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

