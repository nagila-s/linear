import { NextRequest, NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabase-admin";
import { jsonError, mapTestJobToStatus, requireSession } from "@/app/api/test-jobs/_utils";
import type { TestJobRow } from "@/lib/supabase-admin";

type RouteContext = { params: Promise<{ jobId: string }> };

export async function POST(_request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;
  const { jobId } = await context.params;

  try {
    const supabase = getSupabaseAdmin();

    await supabase
      .from("test_pages")
      .update({ status: "pending", error_message: null, attempts: 0 })
      .eq("job_id", jobId)
      .eq("status", "failed");

    await supabase
      .from("test_figures")
      .update({ status: "pending", error_message: null, attempts: 0 })
      .eq("job_id", jobId)
      .eq("status", "failed");

    const { error } = await supabase.rpc("test_enqueue_job", { p_job_id: jobId });
    if (error) return jsonError(error.message, 500);

    const { data } = await supabase.from("test_jobs").select("*").eq("id", jobId).maybeSingle();
    if (!data) return jsonError("Job nao encontrado.", 404);
    return NextResponse.json(mapTestJobToStatus(data as TestJobRow));
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha ao reenfileirar.", 500);
  }
}
