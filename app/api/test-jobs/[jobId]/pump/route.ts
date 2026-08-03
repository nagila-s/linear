import { NextRequest, NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabase-admin";
import { jsonError, requireSession } from "@/app/api/test-jobs/_utils";

type RouteContext = { params: Promise<{ jobId: string }> };

export const maxDuration = 15;

/**
 * Empurra a fila do job: dispara a Edge Function e responde na hora.
 * A funcao se reinvoca sozinha ate esvaziar a fila — nao da para esperar o fim aqui
 * (a Vercel mata a rota e o navegador recebe corpo vazio / Unexpected end of JSON).
 */
export async function POST(_request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;
  const { jobId } = await context.params;

  const baseUrl = process.env.SUPABASE_URL?.trim().replace(/\/+$/, "");
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();
  if (!baseUrl || !key) {
    return jsonError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY ausentes.", 500);
  }

  try {
    const supabase = getSupabaseAdmin();
    const { data: job } = await supabase
      .from("test_jobs")
      .select("status")
      .eq("id", jobId)
      .maybeSingle();
    if (job && ["done", "failed", "cancelled", "partial_success"].includes(job.status)) {
      return NextResponse.json({ ok: true, skipped: true, status: job.status, drained: true });
    }

    // Kick curto: so confirma que a Edge Function aceitou o disparo.
    const response = await fetch(`${baseUrl}/functions/v1/test-run-dispatch`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ job_id: jobId, depth: 0 }),
      signal: AbortSignal.timeout(2_500),
    });

    if (!response.ok) {
      const raw = await response.text();
      return jsonError(
        `Edge Function test-run-dispatch respondeu ${response.status}: ${raw.slice(0, 300)}`,
        502,
      );
    }

    return NextResponse.json({ ok: true, processed: 0, drained: false, kicked: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Falha ao despachar a fila.";
    // Timeout = a funcao ficou processando; isso e o caso feliz.
    const timedOut = /abort|timeout/i.test(message);
    return NextResponse.json({
      ok: true,
      processed: 0,
      drained: false,
      kicked: timedOut,
      note: timedOut ? undefined : message,
    });
  }
}
