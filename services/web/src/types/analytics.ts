export type AnalyticsEvent =
  | { name: 'template_viewed'; params: { template_count: number } }
  | { name: 'template_selected'; params: { template_id: string; template_name: string; total_selected: number } }
  | { name: 'template_deselected'; params: { template_id: string; template_name: string; total_selected: number } }
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
  | { name: 'footer_link_clicked'; params: { link_name: string; url: string } }
  | { name: 'home_linkedin_clicked'; params: Record<string, never> }
  | { name: 'home_github_clicked'; params: Record<string, never> }
  | { name: 'home_resume_clicked'; params: Record<string, never> }
  | { name: 'home_demo_video_watched'; params: { duration_seconds: number } }
  | { name: 'home_scrolled_to_bottom'; params: Record<string, never> }
  | { name: 'facefusion_github_repo_clicked'; params: Record<string, never> };

export interface GtagConfig {
  page_path?: string;
  page_title?: string;
  user_id?: string;
}

