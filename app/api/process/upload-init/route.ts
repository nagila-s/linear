import { NextRequest, NextResponse } from "next/server";
import {
  extractFastApiError,
  fetchFastApi,
  jsonError,
  readFastApiJson,
} from "@/app/api/_utils/fastapi";

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const body = (await request.json()) as {
      isbn?: string;
      filename?: string;
    };

    if (!body.filename?.trim()) {
      return jsonError("Nome do arquivo PDF obrigatorio.", 400);
    }

    const response = await fetchFastApi("/jobs/upload-init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        isbn: body.isbn?.trim() || null,
        filename: body.filename.trim(),
        job_type: "linearizar",
        prompt_version: "v1",
      }),
    });

    const payload = await readFastApiJson(response);
    if (!response.ok) {
      return jsonError(extractFastApiError(payload, "Falha ao preparar upload."), response.status);
    }

    return NextResponse.json(payload);
  } catch (error) {
    const message =
      error instanceof Error && (error.message.includes("fetch") || error.message.includes("FASTAPI_URL"))
        ? "API indisponivel. Verifique FASTAPI_URL na Vercel."
        : error instanceof Error
          ? error.message
          : "Falha ao preparar upload.";
    return jsonError(message, 500);
  }
}
