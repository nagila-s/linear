import { NextRequest, NextResponse } from "next/server";
import {
  extractFastApiError,
  fetchFastApi,
  jsonError,
  readFastApiJson,
} from "@/app/api/_utils/fastapi";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const tab = request.nextUrl.searchParams.get("tab") || "open";
  const limit = request.nextUrl.searchParams.get("limit") || "100";

  try {
    const response = await fetchFastApi(`/queue?tab=${encodeURIComponent(tab)}&limit=${encodeURIComponent(limit)}`);
    const payload = await readFastApiJson(response);
    if (!response.ok) {
      if (response.status === 404) {
        return jsonError(
          "A fila ainda nao esta disponivel nesta API. E preciso publicar a imagem nova da FastAPI na AWS (endpoint /queue).",
          503,
        );
      }
      return jsonError(extractFastApiError(payload, "Falha ao listar a fila."), response.status);
    }
    return NextResponse.json(payload);
  } catch {
    return jsonError(
      "API indisponivel. Verifique FASTAPI_URL na Vercel e se o backend está no ar.",
      503,
    );
  }
}
