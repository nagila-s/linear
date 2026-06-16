import { NextRequest, NextResponse } from "next/server";
import { extractFastApiError, fetchFastApi, jsonError, readFastApiJson } from "@/app/api/_utils/fastapi";

export async function POST(
  _request: NextRequest,
  context: { params: Promise<{ jobId: string }> },
): Promise<NextResponse> {
  const { jobId } = await context.params;
  if (!jobId) return jsonError("jobId obrigatório.", 400);

  try {
    const response = await fetchFastApi(`/jobs/${jobId}/retry`, { method: "POST" });
    const payload = await readFastApiJson(response);

    if (!response.ok) {
      return jsonError(extractFastApiError(payload, "Falha ao reenfileirar processamento."), response.status);
    }

    return NextResponse.json({
      status: "processing",
      progress: 10,
      message: "Processamento reenfileirado. Aguarde...",
    });
  } catch {
    return jsonError(
      "API FastAPI indisponível. Execute `python run_api.py` neste repositório.",
      503,
    );
  }
}
