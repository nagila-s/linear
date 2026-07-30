/** Cliente da área de testes: prepara PDF no browser e cria job no Supabase via BFF Next. */

export type TestJobStatusResponse = {
  jobId: string;
  status: "processing" | "done" | "error";
  progress: number;
  message: string;
  title?: string;
  stats?: {
    pages: number;
    figures: number;
    processedPages: number;
    failedPages: number;
    processedFigures: number;
    failedFigures: number;
  };
  promptHash?: string;
  error?: string;
};

export type StartTestJobOptions = {
  isbn?: string;
  mioloOnly?: boolean;
  promptOverrides: Record<string, string>;
  dpi?: number;
  onPrepareProgress?: (done: number, total: number) => void;
  onUploadProgress?: (done: number, total: number) => void;
};

type CreateJobResponse = {
  jobId: string;
  uploadToken?: string;
  error?: string;
};

type SignedUpload = {
  path: string;
  token: string;
  signedUrl: string;
};

type PreparedPage = {
  pageNumber: number;
  widthPx: number;
  heightPx: number;
  pagePngBlob: Blob;
  figures: Array<{
    figureIndex: number;
    figureKey: string;
    bbox: { x0: number; y0: number; x1: number; y1: number };
    widthPx: number;
    heightPx: number;
    pngBlob: Blob;
    kind: "raster" | "page_fallback";
  }>;
};

async function putBlob(signedUrl: string, blob: Blob, contentType: string): Promise<void> {
  const response = await fetch(signedUrl, {
    method: "PUT",
    headers: {
      "Content-Type": contentType,
      "x-upsert": "true",
    },
    body: blob,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail.slice(0, 200) || `Falha no upload (${response.status}).`);
  }
}

export async function startServerlessTestJob(
  file: File,
  options: StartTestJobOptions,
): Promise<{ jobId: string; message: string }> {
  const dpi = options.dpi ?? 120;
  const { preparePdfPages } = await import("@/lib/test-pdf-prepare");
  const pages = await preparePdfPages(file, {
    dpi,
    maxPages: 30,
    onProgress: options.onPrepareProgress,
  });
  if (!pages.length) {
    throw new Error("PDF sem paginas utilizaveis.");
  }

  const createResponse = await fetch("/api/test-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      isbn: options.isbn,
      miolo_only: Boolean(options.mioloOnly),
      dpi,
      total_pages: pages.length,
      total_figures: pages.reduce((sum, page) => sum + page.figures.length, 0),
      prompt_overrides: options.promptOverrides,
    }),
  });
  const createPayload = (await createResponse.json()) as CreateJobResponse;
  if (!createResponse.ok || !createPayload.jobId) {
    throw new Error(createPayload.error || "Falha ao criar job de teste.");
  }
  const jobId = createPayload.jobId;

  try {
    await uploadManifest(jobId, file, pages, options.onUploadProgress);
    const enqueueResponse = await fetch(`/api/test-jobs/${jobId}/enqueue`, { method: "POST" });
    const enqueuePayload = (await enqueueResponse.json()) as { error?: string; message?: string };
    if (!enqueueResponse.ok) {
      throw new Error(enqueuePayload.error || "Falha ao enfileirar job de teste.");
    }
    return {
      jobId,
      message: enqueuePayload.message || "Teste enfileirado. Processando prompts editados...",
    };
  } catch (error) {
    await fetch(`/api/test-jobs/${jobId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: "failed",
        error_message: error instanceof Error ? error.message : "Falha no upload do manifesto.",
      }),
    }).catch(() => undefined);
    throw error;
  }
}

async function uploadManifest(
  jobId: string,
  file: File,
  pages: PreparedPage[],
  onUploadProgress?: (done: number, total: number) => void,
): Promise<void> {
  const assets: Array<{
    path: string;
    blob: Blob;
    contentType: string;
  }> = [
    {
      path: `${jobId}/original.pdf`,
      blob: file,
      contentType: "application/pdf",
    },
  ];

  for (const page of pages) {
    assets.push({
      path: `${jobId}/pages/p${String(page.pageNumber).padStart(4, "0")}.png`,
      blob: page.pagePngBlob,
      contentType: "image/png",
    });
    for (const figure of page.figures) {
      assets.push({
        path: `${jobId}/figures/p${String(page.pageNumber).padStart(4, "0")}/${figure.figureKey}.png`,
        blob: figure.pngBlob,
        contentType: "image/png",
      });
    }
  }

  const signResponse = await fetch(`/api/test-jobs/${jobId}/sign-uploads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      paths: assets.map((asset) => ({ path: asset.path, contentType: asset.contentType })),
    }),
  });
  const signPayload = (await signResponse.json()) as { uploads?: SignedUpload[]; error?: string };
  if (!signResponse.ok || !signPayload.uploads) {
    throw new Error(signPayload.error || "Falha ao assinar uploads.");
  }
  const byPath = new Map(signPayload.uploads.map((item) => [item.path, item]));

  let done = 0;
  for (const asset of assets) {
    const signed = byPath.get(asset.path);
    if (!signed) throw new Error(`URL assinada ausente para ${asset.path}`);
    await putBlob(signed.signedUrl, asset.blob, asset.contentType);
    done += 1;
    onUploadProgress?.(done, assets.length);
  }

  const registerResponse = await fetch(`/api/test-jobs/${jobId}/register-manifest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pages: pages.map((page) => ({
        page_number: page.pageNumber,
        page_storage_path: `${jobId}/pages/p${String(page.pageNumber).padStart(4, "0")}.png`,
        width_px: page.widthPx,
        height_px: page.heightPx,
        figures: page.figures.map((figure) => ({
          figure_key: figure.figureKey,
          figure_index: figure.figureIndex,
          storage_path: `${jobId}/figures/p${String(page.pageNumber).padStart(4, "0")}/${figure.figureKey}.png`,
          width_px: figure.widthPx,
          height_px: figure.heightPx,
          bbox: figure.bbox,
        })),
      })),
    }),
  });
  const registerPayload = (await registerResponse.json()) as { error?: string };
  if (!registerResponse.ok) {
    throw new Error(registerPayload.error || "Falha ao registrar manifesto.");
  }
}

export async function fetchTestJobStatus(jobId: string): Promise<TestJobStatusResponse> {
  const response = await fetch(`/api/test-jobs/${jobId}/status`);
  const payload = (await response.json()) as TestJobStatusResponse;
  if (!response.ok) {
    throw new Error(payload.error || "Falha ao consultar status do teste.");
  }
  return payload;
}
