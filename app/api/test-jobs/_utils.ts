import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE_NAME } from "@/lib/auth";
import { verifySignedSessionToken } from "@/lib/session";

export function jsonError(message: string, status = 500): NextResponse {
  return NextResponse.json({ error: message }, { status });
}

export async function requireSession(): Promise<{ ok: true } | { ok: false; response: NextResponse }> {
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE_NAME)?.value;
  if (!(await verifySignedSessionToken(token))) {
    return { ok: false, response: jsonError("Sessao invalida ou expirada.", 401) };
  }
  return { ok: true };
}

export function mapTestJobToStatus(job: {
  id: string;
  status: string;
  filename: string;
  total_pages: number;
  total_figures: number;
  processed_pages: number;
  failed_pages: number;
  processed_figures: number;
  failed_figures: number;
  prompt_hash: string;
  error_message: string | null;
}): {
  jobId: string;
  status: "processing" | "done" | "error";
  progress: number;
  message: string;
  title: string;
  stats: {
    pages: number;
    figures: number;
    processedPages: number;
    failedPages: number;
    processedFigures: number;
    failedFigures: number;
  };
  promptHash: string;
} {
  const stats = {
    pages: job.total_pages,
    figures: job.total_figures,
    processedPages: job.processed_pages,
    failedPages: job.failed_pages,
    processedFigures: job.processed_figures,
    failedFigures: job.failed_figures,
  };

  if (job.status === "done") {
    return {
      jobId: job.id,
      status: "done",
      progress: 100,
      message: "Teste concluido. Baixe o JSON para conferir o resultado dos prompts editados.",
      title: job.filename,
      stats,
      promptHash: job.prompt_hash,
    };
  }

  if (job.status === "partial_success") {
    return {
      jobId: job.id,
      status: "done",
      progress: 100,
      message: `Teste parcialmente concluido (${job.failed_pages} pagina(s) / ${job.failed_figures} figura(s) com falha).`,
      title: job.filename,
      stats,
      promptHash: job.prompt_hash,
    };
  }

  if (job.status === "failed" || job.status === "cancelled") {
    return {
      jobId: job.id,
      status: "error",
      progress: 0,
      message: job.error_message || "Falha no teste.",
      title: job.filename,
      stats,
      promptHash: job.prompt_hash,
    };
  }

  const totalUnits = Math.max(1, job.total_pages + job.total_figures);
  const doneUnits = job.processed_pages + job.processed_figures + job.failed_pages + job.failed_figures;
  const progress = Math.min(95, Math.max(5, Math.round((doneUnits / totalUnits) * 100)));

  let message = "Preparando manifesto...";
  if (job.status === "queued") message = "Na fila de testes (Supabase). Aguardando processamento...";
  if (job.status === "running") {
    message = `Processando prompts editados: ${job.processed_pages}/${job.total_pages} pagina(s), ${job.processed_figures}/${job.total_figures} figura(s).`;
  }
  if (job.status === "uploading") message = "Recebendo paginas e figuras...";

  return {
    jobId: job.id,
    status: "processing",
    progress,
    message,
    title: job.filename,
    stats,
    promptHash: job.prompt_hash,
  };
}
