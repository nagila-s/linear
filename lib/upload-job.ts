/** Upload de PDF na producao: URL assinada Supabase (PDF grande, sem limite da Vercel). */

const VERCEL_BFF_MAX_BYTES = 4.5 * 1024 * 1024;

type UploadInitPayload = {
  signed_url: string;
  token: string;
  storage_path: string;
  isbn: string;
  process_version: string;
  bucket: string;
  object_path: string;
};

export function getPublicApiBase(): string | null {
  const url = process.env.NEXT_PUBLIC_FASTAPI_URL?.trim();
  if (!url) return null;
  return url.replace(/\/+$/, "");
}

export function usesDirectUpload(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_FASTAPI_URL?.trim());
}

/** Site HTTPS: upload direto HTTP e proxy Vercel falham acima de ~4,5 MB. */
function shouldUsePresignedUploadInBrowser(): boolean {
  return typeof window !== "undefined" && window.location.protocol === "https:";
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

export async function uploadPdfViaPresigned(
  file: File,
  isbn?: string,
): Promise<{ jobId: string; message?: string }> {
  const initResponse = await fetch("/api/process/upload-init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ isbn, filename: file.name }),
  });
  const initPayload = (await initResponse.json()) as UploadInitPayload & { error?: string };
  if (!initResponse.ok) {
    throw new Error(initPayload.error ?? "Falha ao preparar upload do PDF.");
  }

  const uploadResponse = await fetch(initPayload.signed_url, {
    method: "PUT",
    headers: {
      "Content-Type": file.type || "application/pdf",
      Authorization: `Bearer ${initPayload.token}`,
      "x-upsert": "true",
    },
    body: file,
  });

  if (!uploadResponse.ok) {
    const detail = await uploadResponse.text();
    throw new Error(
      detail.slice(0, 200) ||
        `Falha ao enviar PDF ao storage (${uploadResponse.status}). Verifique limite do Supabase Storage.`,
    );
  }

  const completeResponse = await fetch("/api/process/upload-complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      isbn: initPayload.isbn,
      storage_path: initPayload.storage_path,
      object_path: initPayload.object_path,
      token: initPayload.token,
      filename: file.name,
    }),
  });
  const completePayload = (await completeResponse.json()) as {
    jobId?: string;
    message?: string;
    error?: string;
  };
  if (!completeResponse.ok || !completePayload.jobId) {
    throw new Error(completePayload.error ?? "Falha ao enfileirar processamento.");
  }

  return { jobId: completePayload.jobId, message: completePayload.message };
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
    });
  } catch {
    throw new Error(
      "Nao foi possivel enviar o PDF. Confira NEXT_PUBLIC_FASTAPI_URL e se a API na AWS esta no ar.",
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
  if (shouldUsePresignedUploadInBrowser()) {
    return uploadPdfViaPresigned(file, isbn);
  }

  if (usesDirectUpload()) {
    return uploadPdfToApi(file, isbn);
  }

  if (file.size > VERCEL_BFF_MAX_BYTES) {
    throw new Error(
      "PDF maior que 4,5 MB. Configure NEXT_PUBLIC_FASTAPI_URL ou use o site publicado na Vercel.",
    );
  }

  return uploadPdfViaBff(file, isbn);
}
