import { apiClient } from "../client";
import type { SceneManifest } from "@/lib/scene-manifest";

export interface EditorSceneRead {
  id: string;
  user_id: string;
  name: string;
  manifest: SceneManifest;
  created_at: string;
  updated_at: string;
}

export interface EditorSceneListItem {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface EditorSceneListResponse {
  scenes: EditorSceneListItem[];
}

export interface EditorScenePayload {
  name: string;
  manifest: SceneManifest;
}

export const editorScenesApi = {
  create: async (payload: EditorScenePayload): Promise<EditorSceneRead> => {
    return apiClient.post<EditorSceneRead>("/editor/scenes", payload);
  },

  list: async (): Promise<EditorSceneListResponse> => {
    return apiClient.get<EditorSceneListResponse>("/editor/scenes");
  },

  get: async (id: string): Promise<EditorSceneRead> => {
    return apiClient.get<EditorSceneRead>(`/editor/scenes/${id}`);
  },

  update: async (
    id: string,
    payload: EditorScenePayload,
  ): Promise<EditorSceneRead> => {
    return apiClient.put<EditorSceneRead>(`/editor/scenes/${id}`, payload);
  },

  delete: async (id: string): Promise<void> => {
    return apiClient.delete<void>(`/editor/scenes/${id}`);
  },
};
