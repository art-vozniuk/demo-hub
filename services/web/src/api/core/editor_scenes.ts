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

// Public, anonymous-visitor view of the default scene. The backend
// deliberately omits id/user_id so the shared template can't be loaded or
// overwritten by id — clients only ever get its manifest to render.
export interface DefaultSceneRead {
  name: string;
  manifest: SceneManifest;
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

  // Public read-only — returns the curated default scene shown to anon
  // visitors. Manifest-only: no id is exposed, so it can't be loaded by id.
  getDefault: async (): Promise<DefaultSceneRead> => {
    return apiClient.get<DefaultSceneRead>(`/editor/scenes/default`);
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
