import { NextResponse } from "next/server";
import {
  extractFastApiError,
  fetchFastApi,
  jsonError,
  readFastApiJson,
} from "@/app/api/_utils/fastapi";

export async function GET(): Promise<NextResponse> {
  try {
    const response = await fetchFastApi("/books");
    const payload = await readFastApiJson(response);
    if (!response.ok) {
      return jsonError(extractFastApiError(payload, "Falha ao listar livros."), response.status);
    }
    return NextResponse.json(payload);
  } catch {
    return jsonError(
      "API indisponivel. Execute `python run_api.py` ou verifique FASTAPI_URL.",
      503,
    );
  }
}
