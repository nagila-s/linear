/** Upload de PDF: direto na API publica (evita limite de body da Vercel). */

export function getPublicApiBase(): string | null {
  const url = process.env.NEXT_PUBLIC_FASTAPI_URL?.trim();
  if (!url) return null;
  return url.replace(/\/+$/, "");
}

export function usesDirectUpload(): boolean {
  return Boolean(getPublicApiBase());
}

function apiPrefix(): string {
  return (process.env.NEXT_PUBLIC_API_PREFIX ?? "/api/v1").replace(/\/+$/, "");
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

  const response = await fetch(`${base}${apiPrefix()}/jobs/upload`, {
    method: "POST",
    body: form,
  });

  const payload = (await response.json()) as {
    id?: string;
    detail?: string | { msg?: string }[];
    error?: string;
  };

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
  return uploadPdfViaBff(file, isbn);
}
