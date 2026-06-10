import { NextRequest, NextResponse } from "next/server";
import { fetchFastApi, jsonError, proxyBinary } from "@/app/api/_utils/fastapi";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const { id: jobId } = await context.params;
  const fallbackName = request.nextUrl.searchParams.get("filename") || "livro.json";

  try {
    const response = await fetchFastApi(`/jobs/${jobId}/result-url`, { method: "GET" });
    const payload = (await response.json()) as { download_url?: string; detail?: string };

    if (!response.ok || !payload.download_url) {
      return jsonError(payload.detail ?? "JSON ainda nao disponivel para download.", response.status);
    }

    const fileResponse = await fetch(String(payload.download_url));
    if (!fileResponse.ok) {
      return jsonError("Falha ao baixar JSON final.", 502);
    }

    const proxied = await proxyBinary(fileResponse);
    proxied.headers.set("content-disposition", `attachment; filename="${fallbackName}"`);
    return proxied;
  } catch {
    return jsonError(
      "API indisponivel. Execute `python run_api.py` ou verifique FASTAPI_URL.",
      503,
    );
  }
}
