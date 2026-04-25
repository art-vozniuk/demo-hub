import { apiClient } from "../client";
import { SplatSceneRead } from "../types/core";

export const splatsApi = {
  getScenes: async (): Promise<SplatSceneRead[]> => {
    return apiClient.get<SplatSceneRead[]>("/splats/scenes");
  },
};
