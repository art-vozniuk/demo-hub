import { apiClient } from "../client";
import { RecastTemplateRead } from "../types/core";

export const recastApi = {
  getTemplates: async (): Promise<RecastTemplateRead[]> => {
    return apiClient.get<RecastTemplateRead[]>("/recast/templates");
  },

  getTemplate: async (id: number): Promise<RecastTemplateRead> => {
    return apiClient.get<RecastTemplateRead>(`/recast/templates/${id}`);
  },
};

