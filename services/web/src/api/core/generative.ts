import { apiClient } from "../client";
import { GenerativePresetRead } from "../types/core";

export const generativeApi = {
  getPresets: async (): Promise<GenerativePresetRead[]> => {
    return apiClient.get<GenerativePresetRead[]>("/generative/presets");
  },
  getPreset: async (slug: string): Promise<GenerativePresetRead> => {
    return apiClient.get<GenerativePresetRead>(`/generative/presets/${slug}`);
  },
};
