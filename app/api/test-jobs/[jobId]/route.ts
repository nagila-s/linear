import { NextRequest, NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabase-admin";
import { jsonError, requireSession } from "@/app/api/test-jobs/_utils";

type RouteContext = { params: Promise<{ jobId: string }> };

export async function PATCH(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;
  const { jobId } = await context.params;

  try {
    const body = (await request.json()) as {
      status?: string;
      error_message?: string;
    };
    const supabase = getSupabaseAdmin();
    const patch: Record<string, unknown> = {};
    if (body.status) patch.status = body.status;
    if (body.error_message !== undefined) patch.error_message = body.error_message;
    if (body.status === "failed" || body.status === "cancelled") {
      patch.finished_at = new Date().toISOString();
    }

    const { error } = await supabase.from("test_jobs").update(patch).eq("id", jobId);
    if (error) return jsonError(error.message, 500);
    return NextResponse.json({ ok: true });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha ao atualizar job.", 500);
  }
}

export async function GET(_request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;
  const { jobId } = await context.params;
  try {
    const supabase = getSupabaseAdmin();
    const { data, error } = await supabase.from("test_jobs").select("*").eq("id", jobId).maybeSingle();
    if (error) return jsonError(error.message, 500);
    if (!data) return jsonError("Job nao encontrado.", 404);
    return NextResponse.json(data);
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha ao buscar job.", 500);
  }
}

