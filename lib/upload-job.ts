/** Upload de PDF: direto na API publica (evita limite de body da Vercel). */

const VERCEL_BFF_MAX_BYTES = 4.5 * 1024 * 1024;

export function getPublicApiBase(): string | null {
  const url = process.env.NEXT_PUBLIC_FASTAPI_URL?.trim();
  if (!url) return null;
  const normalized = url.replace(/\/+$/, "");

  // Site HTTPS + API HTTP → browser bloqueia fetch direto; usa proxy na Vercel.
  if (typeof window !== "undefined") {
    const pageIsHttps = window.location.protocol === "https:";
    const apiIsHttp = normalized.startsWith("http://");
    if (pageIsHttps && apiIsHttp) {
      return `${window.location.origin}/backend-api`;
    }
  }

  return normalized;
}

export function usesDirectUpload(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_FASTAPI_URL?.trim());
}

function apiPrefix(): string {
  return (process.env.NEXT_PUBLIC_API_PREFIX ?? "/api/v1").replace(/\/+$/, "");
}

async function readApiJson(response: Response): Promise<{
  id?: string;
  detail?: string | { msg?: string }[];
  error?: string;
}> {
  const contentType = response.headers.get("content-type") ?? "";
  const body = await response.text();
  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(body) as {
        id?: string;
        detail?: string | { msg?: string }[];
        error?: string;
      };
    } catch {
      throw new Error("Resposta invalida da API.");
    }
  }
  throw new Error(body.slice(0, 200) || `Falha na API (${response.status}).`);
}

export async function uploadPdfToApi(
  file: File,
  isbn?: string,
): Promise<{ jobId: string; message?: string }> {
  const base = getPublicApiBase();
  if (!base) {
    throw new Error("NEXT_PUBLIC_FASTAPI_URL nao configurada.");
  }

  const form = new FormData();
  form.append("pdf_file", file);
  if (isbn) form.append("isbn", isbn);
  form.append("job_type", "linearizar");
  form.append("prompt_version", "v1");

  let response: Response;
  try {
    response = await fetch(`${base}${apiPrefix()}/jobs/upload`, {
      method: "POST",
      body: form,
      credentials: "same-origin",
    });
  } catch {
    throw new Error(
      "Nao foi possivel enviar o PDF. Confira FASTAPI_URL na Vercel e se a API na AWS esta no ar.",
    );
  }

  const payload = await readApiJson(response);

  if (!response.ok) {
    const detail =
      typeof payload.detail === "string"
        ? payload.detail
        : Array.isArray(payload.detail)
          ? payload.detail.map((d) => d.msg ?? "").join("; ")
          : payload.error;
    throw new Error(detail || "Falha ao enviar PDF para a API.");
  }

  if (!payload.id) {
    throw new Error("Resposta da API sem id do job.");
  }

  return { jobId: String(payload.id), message: "Analisando estrutura..." };
}

export async function uploadPdfViaBff(
  file: File,
  isbn?: string,
): Promise<{ jobId: string; message?: string }> {
  const formData = new FormData();
  formData.append("pdf", file);
  if (isbn) formData.append("isbn", isbn);
  formData.append("linearize", "true");
  formData.append("contextualize", "false");

  const response = await fetch("/api/process", { method: "POST", body: formData });
  const payload = (await response.json()) as {
    jobId?: string;
    message?: string;
    error?: string;
  };

  if (!response.ok || !payload.jobId) {
    throw new Error(payload.error ?? "Nao foi possivel iniciar o processamento.");
  }

  return { jobId: payload.jobId, message: payload.message };
}

export async function startPdfJob(
  file: File,
  isbn?: string,
): Promise<{ jobId: string; message?: string }> {
  if (usesDirectUpload()) {
    return uploadPdfToApi(file, isbn);
  }

  if (file.size > VERCEL_BFF_MAX_BYTES) {
    throw new Error(
      "PDF maior que 4,5 MB. Configure NEXT_PUBLIC_FASTAPI_URL na Vercel (URL da API na AWS).",
    );
  }

  return uploadPdfViaBff(file, isbn);
}
