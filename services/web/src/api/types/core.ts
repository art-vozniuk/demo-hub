export interface RecastTemplateRead {
  id: number;
  name: string | null;
  description: string | null;
  url: string;
  created_at: string;
  updated_at: string;
}

export interface SplatSceneRead {
  id: number;
  slug: string;
  title: string;
  description: string | null;
  image_url: string;
  scene_url: string;
  // vec3 — passed straight through to the renderer iframe as
  // ?eye=x,y,z and ?fwd=x,y,z
  camera_eye: [number, number, number];
  camera_fwd: [number, number, number];
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface GenerativePresetRead {
  id: number;
  slug: string;
  title: string;
  description: string | null;
  preview_image_url: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}
