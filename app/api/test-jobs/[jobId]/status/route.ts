import { NextRequest, NextResponse } from "next/server";
import { getSupabaseAdmin, type TestJobRow } from "@/lib/supabase-admin";
import { jsonError, mapTestJobToStatus, requireSession } from "@/app/api/test-jobs/_utils";

type RouteContext = { params: Promise<{ jobId: string }> };

export async function GET(_request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;
  const { jobId } = await context.params;

  try {
    const supabase = getSupabaseAdmin();
    const { data, error } = await supabase.from("test_jobs").select("*").eq("id", jobId).maybeSingle();
    if (error) return jsonError(error.message, 500);
    if (!data) return jsonError("Job nao encontrado.", 404);
    return NextResponse.json(mapTestJobToStatus(data as TestJobRow));
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha ao consultar status.", 500);
  }
}
