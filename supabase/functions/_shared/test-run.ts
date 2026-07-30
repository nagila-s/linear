import { createClient, type SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.49.1";

export const TEST_RUNS_BUCKET = "test-runs";

export type QueueMessage = {
  kind: "classify_page" | "linearize_page" | "describe_figure" | "finalize";
  job_id: string;
  page_id?: string;
  page_number?: number;
  figure_id?: string;
  figure_key?: string;
};

export function getServiceClient(): SupabaseClient {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) throw new Error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY ausentes.");
  return createClient(url, key, { auth: { persistSession: false } });
}

export const PAGE_TYPES = new Set([
  "capa",
  "autores",
  "ficha",
  "apresentacao",
  "conheca",
  "sumario",
  "hino",
  "referencias",
  "contracapa",
  "conteudo",
]);

export const PROMPT_FILES: Record<string, string> = {
  capa: "capa.txt",
  autores: "autores.txt",
  ficha: "ficha.txt",
  apresentacao: "apresentacao.txt",
  conheca: "conheca.txt",
  sumario: "sumario.txt",
  hino: "hino.txt",
  referencias: "referencias.txt",
  contracapa: "contracapa.txt",
  conteudo: "base.txt",
};

export function normalizePageType(raw: string): string {
  let cleaned = (raw || "").trim().toLowerCase();
  cleaned = cleaned.split(/\s+/)[0] ?? "";
  cleaned = cleaned.replace(/[.,;:!?"']+/g, "");
  return PAGE_TYPES.has(cleaned) ? cleaned : "conteudo";
}

export function shouldClassify(pageNumber: number, totalPages: number, windowStart = 20, windowEnd = 15): boolean {
  if (totalPages <= 0 || pageNumber <= 0) return false;
  return pageNumber <= windowStart || pageNumber >= totalPages - windowEnd + 1;
}

export function getPromptFromSnapshot(
  snapshot: Record<string, string>,
  pageType: string,
): { prompt: string; promptFile: string } {
  const normalized = normalizePageType(pageType);
  const filename = PROMPT_FILES[normalized] ?? "base.txt";
  const shared = (snapshot["_shared_rules.txt"] || "").trim();
  let prompt = (snapshot[filename] || "").trim();
  if (!prompt && normalized !== "conteudo") {
    prompt = (snapshot["base.txt"] || "").trim();
  }
  if (!prompt) {
    throw new Error(`Prompt ausente no snapshot: ${filename}`);
  }
  prompt = prompt.replaceAll("{{SHARED_RULES}}", shared).trim();
  return { prompt, promptFile: filename };
}

export async function sha256Hex(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function validateLinearizationRoot(data: unknown): { ok: boolean; error?: string } {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return { ok: false, error: "Resposta nao e um objeto JSON." };
  }
  const obj = data as Record<string, unknown>;
  if (typeof obj.tipo_pagina !== "string" || !obj.tipo_pagina.trim()) {
    return { ok: false, error: 'Campo obrigatorio ausente: "tipo_pagina".' };
  }
  if (!("pagina" in obj)) {
    return { ok: false, error: 'Campo obrigatorio ausente: "pagina".' };
  }
  if (!Array.isArray(obj.conteudo)) {
    return { ok: false, error: 'Campo obrigatorio ausente ou invalido: "conteudo".' };
  }
  return { ok: true };
}

export async function signedUrl(
  supabase: SupabaseClient,
  path: string,
  expiresIn = 600,
): Promise<string> {
  const { data, error } = await supabase.storage.from(TEST_RUNS_BUCKET).createSignedUrl(path, expiresIn);
  if (error || !data?.signedUrl) throw new Error(error?.message || `Falha ao assinar ${path}`);
  return data.signedUrl;
}

export async function downloadBytes(supabase: SupabaseClient, path: string): Promise<Uint8Array> {
  const { data, error } = await supabase.storage.from(TEST_RUNS_BUCKET).download(path);
  if (error || !data) throw new Error(error?.message || `Falha ao baixar ${path}`);
  return new Uint8Array(await data.arrayBuffer());
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]!);
  return btoa(binary);
}

export async function enqueue(
  supabase: SupabaseClient,
  payload: QueueMessage,
): Promise<void> {
  const { error } = await supabase.rpc("test_enqueue_stage", { p_payload: payload });
  if (error) throw new Error(error.message);
}

export async function refreshCounters(supabase: SupabaseClient, jobId: string): Promise<void> {
  const { error } = await supabase.rpc("test_refresh_job_counters", { p_job_id: jobId });
  if (error) throw new Error(error.message);
}

export async function archiveMessage(supabase: SupabaseClient, msgId: number): Promise<void> {
  const { error } = await supabase.rpc("test_archive_message", { p_msg_id: msgId });
  if (error) throw new Error(error.message);
}

export type QueueRow = {
  msg_id: number;
  read_ct: number;
  message: QueueMessage;
};

export async function readQueue(
  supabase: SupabaseClient,
  vt = 120,
  qty = 3,
): Promise<QueueRow[]> {
  const { data, error } = await supabase.rpc("test_read_queue", { p_vt: vt, p_qty: qty });
  if (error) throw new Error(error.message);
  return (data || []) as QueueRow[];
}
