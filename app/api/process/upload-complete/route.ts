import { NextRequest, NextResponse } from "next/server";
import { fetchFastApi, jsonError } from "@/app/api/_utils/fastapi";

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const body = (await request.json()) as {
      isbn?: string;
      storage_path?: string;
      object_path?: string;
      token?: string;
      filename?: string;
    };

    if (!body.isbn || !body.storage_path || !body.object_path || !body.token || !body.filename) {
      return jsonError("Dados incompletos para concluir o upload.", 400);
    }

    const response = await fetchFastApi("/jobs/upload-complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        isbn: body.isbn,
        storage_path: body.storage_path,
        object_path: body.object_path,
        token: body.token,
        filename: body.filename,
        job_type: "linearizar",
        prompt_version: "v1",
      }),
    });

    const payload = await response.json();
    if (!response.ok) {
      const detail = typeof payload.detail === "string" ? payload.detail : "Falha ao enfileirar job.";
      return jsonError(detail, response.status);
    }

    return NextResponse.json({
      jobId: String(payload.id),
      message: "Analisando estrutura...",
    });
  } catch (error) {
    const message =
      error instanceof Error && (error.message.includes("fetch") || error.message.includes("FASTAPI_URL"))
        ? "API indisponivel. Verifique FASTAPI_URL na Vercel."
        : error instanceof Error
          ? error.message
          : "Falha ao concluir upload.";
    return jsonError(message, 500);
  }
}
