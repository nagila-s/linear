import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let cached: SupabaseClient | null = null;

export function getSupabaseAdmin(): SupabaseClient {
  if (cached) return cached;
  const url = process.env.SUPABASE_URL?.trim();
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();
  if (!url || !key) {
    throw new Error("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY sao obrigatorias para a area de testes.");
  }
  cached = createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return cached;
}

export const TEST_RUNS_BUCKET = "test-runs";

export type TestJobStatus =
  | "uploading"
  | "queued"
  | "running"
  | "partial_success"
  | "done"
  | "failed"
  | "cancelled";

export type TestPageStatus = "pending" | "queued" | "running" | "ok" | "failed" | "skipped";

export type TestFigureStatus = "pending" | "queued" | "running" | "ok" | "failed" | "skipped";

export type TestJobRow = {
  id: string;
  isbn: string;
  filename: string;
  status: TestJobStatus;
  miolo_only: boolean;
  dpi: number;
  total_pages: number;
  total_figures: number;
  processed_pages: number;
  failed_pages: number;
  processed_figures: number;
  failed_figures: number;
  prompt_snapshot: Record<string, string>;
  prompt_hash: string;
  final_storage_path: string | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type TestPageRow = {
  id: string;
  job_id: string;
  page_number: number;
  status: TestPageStatus;
  page_type: string | null;
  page_storage_path: string;
  width_px: number | null;
  height_px: number | null;
  prompt_file: string | null;
  prompt_hash: string | null;
  openai_model: string | null;
  openai_response_id: string | null;
  content: Record<string, unknown> | null;
  error_message: string | null;
  attempts: number;
  max_attempts: number;
};

export type TestFigureRow = {
  id: string;
  job_id: string;
  page_id: string;
  page_number: number;
  figure_key: string;
  figure_index: number;
  status: TestFigureStatus;
  storage_path: string;
  width_px: number | null;
  height_px: number | null;
  bbox: Record<string, number> | null;
  context: string | null;
  description: string | null;
  dorina_payload: Record<string, unknown> | null;
  error_message: string | null;
  attempts: number;
  max_attempts: number;
};
