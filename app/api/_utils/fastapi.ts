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

type FastApiErrorPayload = {
  detail?: string | { msg?: string; loc?: unknown[] }[];
  error?: string;
};

export function extractFastApiError(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const body = payload as FastApiErrorPayload;
  if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
  if (Array.isArray(body.detail)) {
    const messages = body.detail
      .map((item) => (typeof item?.msg === "string" ? item.msg : ""))
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  if (typeof body.error === "string" && body.error.trim()) return body.error;
  return fallback;
}

export async function readFastApiJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text.trim()) return {};
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { detail: text.slice(0, 200) || `Resposta invalida da API (${response.status}).` };
  }
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

const STAGE_USER_MESSAGES: Record<string, string> = {
  queued: "Aguardando na fila de processamento...",
  preprocess: "Analisando a estrutura do PDF...",
  pages: "Preparando as páginas do livro...",
  extract: "Preparando as páginas do livro...",
  linearize: "Linearizando o conteúdo com IA...",
  describe: "Linearizando o conteúdo com IA...",
  assemble: "Montando o arquivo final...",
  done: "Linearização concluída! Você já pode baixar o JSON.",
};

const STAGE_PROGRESS: Record<string, number> = {
  queued: 10,
  preprocess: 25,
  pages: 35,
  extract: 35,
  linearize: 65,
  describe: 65,
  assemble: 90,
  done: 100,
};

function isActiveStage(stage: string): boolean {
  return Boolean(stage) && stage !== "preprocess" && stage !== "queued";
}

function mapStageMessage(etapa: string | undefined, status: string): string {
  const rawStatus = status.toLowerCase();
  const stage = (etapa ?? "").toLowerCase().trim();

  if (rawStatus === "done") {
    return STAGE_USER_MESSAGES.done;
  }

  if (rawStatus === "queued") {
    return STAGE_USER_MESSAGES.queued;
  }

  if ((rawStatus === "running" || rawStatus === "retrying") && !isActiveStage(stage)) {
    return "Linearizando o livro com IA...";
  }

  if (stage && STAGE_USER_MESSAGES[stage]) {
    return STAGE_USER_MESSAGES[stage];
  }

  return "Processando livro...";
}

function mapStageProgress(etapa: string | undefined, status: string): number {
  const rawStatus = status.toLowerCase();
  const stage = (etapa ?? "").toLowerCase().trim();

  if (rawStatus === "done") return 100;

  if ((rawStatus === "running" || rawStatus === "retrying") && !isActiveStage(stage)) {
    return 55;
  }

  if (stage && STAGE_PROGRESS[stage] !== undefined) return STAGE_PROGRESS[stage];

  const progressByStatus: Record<string, number> = {
    queued: 10,
    running: 55,
    retrying: 35,
    partial_success: 85,
  };

  return progressByStatus[rawStatus] ?? 40;
}

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
      message: mapStageMessage(job.etapa_atual, raw),
      title: job.metadata?.title,
    };
  }

  if (raw === "failed") {
    return {
      status: "error",
      progress: 0,
      message: job.error_message || "Falha no processamento. Tente novamente.",
      title: job.metadata?.title,
    };
  }

  return {
    status: "processing",
    progress: mapStageProgress(job.etapa_atual, raw),
    message: mapStageMessage(job.etapa_atual, raw),
    title: job.metadata?.title,
  };
}
