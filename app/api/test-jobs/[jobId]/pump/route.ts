import { NextRequest, NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabase-admin";
import { jsonError, requireSession } from "@/app/api/test-jobs/_utils";

type RouteContext = { params: Promise<{ jobId: string }> };

export const maxDuration = 60;

/**
 * Empurra a fila do job chamando a Edge Function e esperando a resposta.
 * O navegador chama isto junto do polling, entao o teste anda sem depender de cron.
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
      return NextResponse.json({ ok: true, skipped: true, status: job.status });
    }

    const response = await fetch(`${baseUrl}/functions/v1/test-run-dispatch`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ job_id: jobId }),
      signal: AbortSignal.timeout(55_000),
    });

    const raw = await response.text();
    if (!response.ok) {
      return jsonError(
        `Edge Function test-run-dispatch respondeu ${response.status}: ${raw.slice(0, 300)}`,
        502,
      );
    }

    let payload: { processed?: number; drained?: boolean } = {};
    try {
      payload = JSON.parse(raw) as typeof payload;
    } catch {
      return jsonError(`Resposta nao-JSON da Edge Function: ${raw.slice(0, 200)}`, 502);
    }

    return NextResponse.json({
      ok: true,
      processed: payload.processed ?? 0,
      drained: Boolean(payload.drained),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Falha ao despachar a fila.";
    // Timeout aqui e esperado em lotes longos; o proximo pump continua de onde parou.
    return NextResponse.json({ ok: true, processed: 0, drained: false, note: message });
  }
}
