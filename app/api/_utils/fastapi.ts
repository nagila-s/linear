import { NextResponse } from "next/server";

function resolveFastApiOrigin(): string {
  const configured = process.env.FASTAPI_URL?.trim();
  if (configured) return configured.replace(/\/+$/, "");
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "FASTAPI_URL não configurada. Defina a URL pública da API FastAPI nas variáveis da Vercel.",
    );
  }
  return "http://127.0.0.1:8000";
}

const API_PREFIX = (process.env.API_PREFIX ?? "/api/v1").replace(/\/+$/, "");

export function fastApiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${resolveFastApiOrigin()}${API_PREFIX}${normalized}`;
}

export async function fetchFastApi(path: string, init?: RequestInit): Promise<Response> {
  return fetch(fastApiUrl(path), init);
}

export function jsonError(message: string, status = 500): NextResponse {
  return NextResponse.json({ error: message }, { status });
}

export async function proxyBinary(response: Response): Promise<NextResponse> {
  const blob = await response.arrayBuffer();
  const headers = new Headers();
  const contentType = response.headers.get("content-type");
  const disposition = response.headers.get("content-disposition");
  if (contentType) headers.set("content-type", contentType);
  if (disposition) headers.set("content-disposition", disposition);
  return new NextResponse(blob, { status: response.status, headers });
}

export type FastApiJob = {
  id: string;
  isbn: string;
  status: string;
  etapa_atual: string;
  error_message?: string | null;
  metadata?: { filename?: string; title?: string };
};

export function mapJobToProcessStatus(job: FastApiJob): {
  status: "processing" | "done" | "error";
  progress: number;
  message: string;
  title?: string;
} {
  const raw = String(job.status).toLowerCase();

  if (raw === "done") {
    return {
      status: "done",
      progress: 100,
      message: job.etapa_atual || "Processamento concluído.",
      title: job.metadata?.title,
    };
  }

  if (raw === "failed") {
    return {
      status: "error",
      progress: 0,
      message: job.error_message || job.etapa_atual || "Falha no processamento.",
      title: job.metadata?.title,
    };
  }

  const progressByStatus: Record<string, number> = {
    queued: 15,
    running: 55,
    retrying: 35,
    partial_success: 85,
  };

  return {
    status: "processing",
    progress: progressByStatus[raw] ?? 40,
    message: job.etapa_atual || "Processando...",
    title: job.metadata?.title,
  };
}
