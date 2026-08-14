export type AnalyticsEvent =
  | { name: 'template_viewed'; params: { template_count: number } }
  | { name: 'template_selected'; params: { template_id: number; template_name: string | null; total_selected: number } }
  | { name: 'template_deselected'; params: { template_id: number; template_name: string | null; total_selected: number } }
  | { name: 'max_templates_reached'; params: { max_allowed: number } }
  | { name: 'generate_clicked'; params: { template_count: number; source: 'face_fusion' } }
  | { name: 'image_upload_started'; params: Record<string, never> }
  | { name: 'image_uploaded'; params: { file_size_kb: number; file_type: string } }
  | { name: 'generate_initiated'; params: { template_count: number; has_auth: boolean } }
  | { name: 'auth_required'; params: { redirect_from: string } }
  | { name: 'auth_completed'; params: { provider: string } }
  | { name: 'generation_started'; params: { pipeline_count: number; trace_id: string } }
  | { name: 'generation_completed'; params: { pipeline_id: string; duration_seconds?: number } }
  | { name: 'generation_failed'; params: { pipeline_id: string; error: string } }
  | { name: 'try_other_templates_clicked'; params: { from_status: 'success' | 'error' } }
  | { name: 'back_to_templates'; params: { source: string } }
  | { name: 'nav_home_clicked'; params: Record<string, never> }
  | { name: 'nav_facefusion_clicked'; params: Record<string, never> }
  | { name: 'nav_generative_clicked'; params: Record<string, never> }
  | { name: 'nav_renderer_clicked'; params: Record<string, never> }
  | { name: 'nav_editor_clicked'; params: Record<string, never> }
  | { name: 'nav_sharp_clicked'; params: Record<string, never> }
  | { name: 'nav_trellis_clicked'; params: Record<string, never> }
  | { name: 'sharp_generate_started'; params: { pipeline_id: string } }
  | { name: 'transcriber_run_started'; params: { pipeline_id: string; model: string; llm_cleanup: boolean; source_kind: 'audio' | 'video' } }
  | { name: 'generative_preset_opened'; params: { preset_slug: string } }
  | { name: 'generative_generate_started'; params: { preset_slug: string; pipeline_id: string } }
  | { name: 'generative_refine_face_started'; params: { preset_slug: string; flux_pipeline_id: string; refine_pipeline_id: string } }
  | { name: 'generative_github_repo_clicked'; params: Record<string, never> }
  | { name: 'footer_link_clicked'; params: { link_name: string; url: string } }
  | { name: 'home_linkedin_clicked'; params: Record<string, never> }
  | { name: 'home_github_clicked'; params: Record<string, never> }
  | { name: 'home_resume_clicked'; params: Record<string, never> }
  | { name: 'home_demo_video_watched'; params: { duration_seconds: number } }
  | { name: 'home_scrolled_to_bottom'; params: Record<string, never> }
  | { name: 'facefusion_github_repo_clicked'; params: Record<string, never> }
  | { name: 'renderer_github_repo_clicked'; params: Record<string, never> }
  | { name: 'renderer_scene_opened'; params: { scene_slug: string } }
  | { name: 'renderer_scene_back'; params: { scene_slug: string } }
  | { name: 'my_pipelines_viewed'; params: Record<string, never> }
  | { name: 'pipeline_share_opened'; params: { pipeline_id: string } }
  | { name: 'pipeline_share_copy'; params: { pipeline_id: string } }
  | { name: 'pipeline_share_native'; params: { pipeline_id: string } }
  | { name: 'pipeline_share_viewed'; params: { pipeline_id: string; pipeline_name: string } }
  | { name: 'pipeline_share_try_clicked'; params: { pipeline_id: string; pipeline_name: string } }
  | { name: 'editor_generate_splat_opened'; params: Record<string, never> }
  | { name: 'editor_generate_splat_flux_submitted'; params: { pipeline_id: string; has_init_image: boolean } }
  | { name: 'editor_generate_splat_flux_completed'; params: { pipeline_id: string } }
  | { name: 'editor_generate_splat_flux_failed'; params: { pipeline_id: string; error: string } }
  | { name: 'editor_generate_splat_confirmed'; params: { name: string } }
  | { name: 'editor_generate_splat_sharp_started'; params: { pipeline_id: string } }
  | { name: 'editor_generate_splat_sharp_completed'; params: { pipeline_id: string } }
  | { name: 'editor_generate_splat_sharp_failed'; params: { pipeline_id: string; error: string } }
  | { name: 'editor_generate_splat_cancelled'; params: { phase: string } };

export interface GtagConfig {
  page_path?: string;
  page_title?: string;
  user_id?: string;
}

