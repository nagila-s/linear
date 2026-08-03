import { NextRequest, NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabase-admin";
import { jsonError, requireSession } from "@/app/api/test-jobs/_utils";

type RouteContext = { params: Promise<{ jobId: string }> };

export async function POST(_request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;
  const { jobId } = await context.params;

  try {
    const supabase = getSupabaseAdmin();
    const { data: pages, error: pagesError } = await supabase
      .from("test_pages")
      .select("id")
      .eq("job_id", jobId);
    if (pagesError) return jsonError(pagesError.message, 500);
    if (!pages?.length) {
      return jsonError("Manifesto incompleto: nenhuma pagina registrada.", 400);
    }

    const { error } = await supabase.rpc("test_enqueue_job", { p_job_id: jobId });
    if (error) return jsonError(error.message, 500);

    // Disparo em background: a Edge Function se reinvoca ate esvaziar a fila.
    // Nao esperamos a resposta — esperar aqui estourava o limite da Vercel e
    // devolvia corpo vazio ao navegador ("Unexpected end of JSON input").
    const baseUrl = process.env.SUPABASE_URL?.trim().replace(/\/+$/, "");
    const key = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();
    if (baseUrl && key) {
      void fetch(`${baseUrl}/functions/v1/test-run-dispatch`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${key}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ depth: 0 }),
      }).catch(() => undefined);
    }

    return NextResponse.json({
      ok: true,
      message: "Teste enfileirado no Supabase. Os prompts editados serao usados na OpenAI/Dorina.",
    });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha ao enfileirar.", 500);
  }
}
