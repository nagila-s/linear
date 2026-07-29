import { NextRequest, NextResponse } from "next/server";
import { extractFastApiError, fetchFastApi, jsonError } from "@/app/api/_utils/fastapi";

export const maxDuration = 300;

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const incoming = await request.formData();
    const file = incoming.get("pdf_file") ?? incoming.get("pdf");
    if (!(file instanceof File)) {
      return jsonError("Arquivo PDF não enviado.", 400);
    }

    const isbn = String(incoming.get("isbn") ?? "").trim();
    const mioloOnly = String(incoming.get("miolo_only") ?? "false") === "true";
    const promptOverrides = String(incoming.get("prompt_overrides") ?? "").trim();

    const backendForm = new FormData();
    backendForm.append("pdf_file", file);
    if (isbn) backendForm.append("isbn", isbn);
    backendForm.append("miolo_only", mioloOnly ? "true" : "false");
    if (promptOverrides) backendForm.append("prompt_overrides", promptOverrides);

    const response = await fetchFastApi("/jobs/test-run", {
      method: "POST",
      body: backendForm,
    });

    const text = await response.text();
    let payload: unknown = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { detail: text.slice(0, 300) };
    }

    if (!response.ok) {
      return jsonError(extractFastApiError(payload, "Falha ao rodar o teste."), response.status);
    }

    return NextResponse.json(payload);
  } catch (error) {
    const message =
      error instanceof Error && (error.message.includes("fetch") || error.message.includes("FASTAPI_URL"))
        ? "API indisponível. Verifique FASTAPI_URL e se a API está no ar."
        : error instanceof Error
          ? error.message
          : "Falha ao rodar o teste.";
    return jsonError(message, 500);
  }
}
