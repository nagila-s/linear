/** Upload de PDF na producao: URL assinada Supabase (PDF grande, sem limite da Vercel). */

const VERCEL_BFF_MAX_BYTES = 4.5 * 1024 * 1024;

export type StartPdfJobOptions = {
  mioloOnly?: boolean;
  literario?: boolean;
  modelo?: string;
  testRun?: boolean;
  promptOverrides?: Record<string, string>;
};

type UploadInitPayload = {
  signed_url: string;
  token: string;
  storage_path: string;
  isbn: string;
  process_version: string;
  bucket: string;
  object_path: string;
};

/** Site HTTPS: upload direto HTTP e proxy Vercel falham acima de ~4,5 MB. */
function shouldUsePresignedUploadInBrowser(): boolean {
  return typeof window !== "undefined" && window.location.protocol === "https:";
}

function hasPromptOverrides(options: StartPdfJobOptions): boolean {
  return Boolean(options.promptOverrides && Object.keys(options.promptOverrides).length > 0);
}

async function readBrowserJson<T extends { error?: string }>(
  response: Response,
  context: string,
): Promise<T> {
  const raw = await response.text();
  if (!raw.trim()) {
    throw new Error(
      `${context}: resposta vazia (HTTP ${response.status}). ` +
        "Verifique FASTAPI_URL / NEXT_PUBLIC_FASTAPI_URL na Vercel.",
    );
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new Error(
      `${context}: resposta nao-JSON (HTTP ${response.status}): ${raw.slice(0, 200)}`,
    );
  }
}

export async function uploadPdfViaPresigned(
  file: File,
  isbn?: string,
  options: StartPdfJobOptions = {},
): Promise<{ jobId: string; message?: string }> {
  const mioloOnly = Boolean(options.mioloOnly);
  const literario = Boolean(options.literario);
  const testRun = Boolean(options.testRun) || hasPromptOverrides(options);
  const initResponse = await fetch("/api/process/upload-init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      isbn,
      filename: file.name,
      miolo_only: mioloOnly,
      literario,
      ...(options.modelo ? { modelo: options.modelo } : {}),
    }),
  });
  const initPayload = await readBrowserJson<UploadInitPayload & { error?: string }>(
    initResponse,
    "Preparar upload",
  );
  if (!initResponse.ok) {
    throw new Error(initPayload.error ?? `Falha ao preparar upload do PDF (${initResponse.status}).`);
  }
  if (!initPayload.signed_url || !initPayload.token || !initPayload.storage_path) {
    throw new Error("Resposta incompleta ao preparar upload do PDF.");
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

  const completeBody: Record<string, unknown> = {
    isbn: initPayload.isbn,
    storage_path: initPayload.storage_path,
    object_path: initPayload.object_path,
    token: initPayload.token,
    filename: file.name,
    miolo_only: mioloOnly,
    literario,
    test_run: testRun,
    ...(options.modelo ? { modelo: options.modelo } : {}),
  };
  if (hasPromptOverrides(options)) {
    completeBody.prompt_overrides = options.promptOverrides;
  }
  try {
    const { countPdfPages } = await import("@/lib/pdf-page-count");
    const pageCount = await countPdfPages(file);
    if (pageCount > 0) completeBody.page_count = pageCount;
  } catch {
    // Estimativa na fila fica sem page_count até o worker backfillar.
  }

  const completeResponse = await fetch("/api/process/upload-complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(completeBody),
  });
  const completePayload = await readBrowserJson<{
    jobId?: string;
    message?: string;
    error?: string;
  }>(completeResponse, "Enfileirar processamento");
  if (!completeResponse.ok || !completePayload.jobId) {
    throw new Error(
      completePayload.error ??
        `Falha ao enfileirar processamento (${completeResponse.status}).`,
    );
  }

  return { jobId: completePayload.jobId, message: completePayload.message };
}

export async function uploadPdfViaBff(
  file: File,
  isbn?: string,
  options: StartPdfJobOptions = {},
): Promise<{ jobId: string; message?: string }> {
  const formData = new FormData();
  formData.append("pdf", file);
  if (isbn) formData.append("isbn", isbn);
  formData.append("linearize", "true");
  formData.append("contextualize", "false");
  formData.append("miolo_only", options.mioloOnly ? "true" : "false");
  formData.append("literario", options.literario ? "true" : "false");
  if (options.modelo) formData.append("modelo", options.modelo);
  const testRun = Boolean(options.testRun) || hasPromptOverrides(options);
  formData.append("test_run", testRun ? "true" : "false");
  if (hasPromptOverrides(options)) {
    formData.append("prompt_overrides", JSON.stringify(options.promptOverrides));
  }

  const response = await fetch("/api/process", { method: "POST", body: formData });
  const payload = await readBrowserJson<{
    jobId?: string;
    message?: string;
    error?: string;
  }>(response, "Iniciar processamento");

  if (!response.ok || !payload.jobId) {
    throw new Error(payload.error ?? "Nao foi possivel iniciar o processamento.");
  }

  return { jobId: payload.jobId, message: payload.message };
}

export async function startPdfJob(
  file: File,
  isbn?: string,
  options: StartPdfJobOptions = {},
): Promise<{ jobId: string; message?: string }> {
  // A API exige LINEAR_API_KEY, que só existe no servidor: o navegador nunca fala com ela direto.
  if (shouldUsePresignedUploadInBrowser()) {
    return uploadPdfViaPresigned(file, isbn, options);
  }

  if (file.size > VERCEL_BFF_MAX_BYTES) {
    throw new Error("PDF maior que 4,5 MB. Use o site publicado na Vercel (upload por URL assinada).");
  }

  return uploadPdfViaBff(file, isbn, options);
}
