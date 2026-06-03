import { NextRequest, NextResponse } from "next/server";
import {
  fetchFastApi,
  jsonError,
  mapJobToProcessStatus,
  type FastApiJob,
} from "@/app/api/_utils/fastapi";

export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ jobId: string }> },
): Promise<NextResponse> {
  const { jobId } = await context.params;
  if (!jobId) return jsonError("jobId obrigatório.", 400);

  try {
    const response = await fetchFastApi(`/jobs/${jobId}`, { method: "GET" });
    const payload = (await response.json()) as FastApiJob & { detail?: string };

    if (!response.ok) {
      return jsonError(payload.detail ?? "Falha ao consultar status.", response.status);
    }

    const mapped = mapJobToProcessStatus(payload);
    return NextResponse.json({
      ...mapped,
      fileName: payload.metadata?.filename,
    });
  } catch {
    return jsonError(
      "API FastAPI indisponível. Execute `python run_api.py` neste repositório.",
      503,
    );
  }
}
