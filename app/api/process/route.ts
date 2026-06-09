import { NextRequest, NextResponse } from "next/server";
import { fetchFastApi, jsonError } from "@/app/api/_utils/fastapi";

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const incoming = await request.formData();
    const file = incoming.get("pdf");
    if (!(file instanceof File)) {
      return jsonError("Arquivo PDF não enviado.", 400);
    }

    const linearize = String(incoming.get("linearize") ?? "true") === "true";
    const contextualize = String(incoming.get("contextualize") ?? "false") === "true";

    if (!linearize) {
      return jsonError(
        "No momento só está disponível a ação de linearização. Marque «Linearizar e enviar para a Plataforma Braille».",
        400,
      );
    }

    if (contextualize) {
      return jsonError(
        "Contextualização (Avalia) ainda não está habilitada na API. Use apenas linearização.",
        400,
      );
    }

    const isbnInput = String(incoming.get("isbn") ?? "").trim();

    const backendForm = new FormData();
    backendForm.append("pdf_file", file);
    if (isbnInput) {
      backendForm.append("isbn", isbnInput);
    }
    backendForm.append("job_type", "linearizar");
    backendForm.append("prompt_version", "v1");

    const response = await fetchFastApi("/jobs/upload", {
      method: "POST",
      body: backendForm,
    });

    const payload = await response.json();
    if (!response.ok) {
      const detail =
        typeof payload.detail === "string"
          ? payload.detail
          : "Falha ao criar job de processamento.";
      return jsonError(detail, response.status);
    }

    return NextResponse.json({
      jobId: String(payload.id),
      message: "Analisando estrutura...",
    });
  } catch (error) {
    const message =
      error instanceof Error
        ? error.message.includes("fetch") || error.message.includes("FASTAPI_URL")
          ? process.env.NODE_ENV === "production"
            ? "API FastAPI indisponível. Verifique FASTAPI_URL e se o backend está no ar."
            : "API FastAPI indisponível. Execute `python run_api.py` neste repositório."
          : error.message
        : "Falha ao iniciar processamento.";
    return jsonError(message, 500);
  }
}
