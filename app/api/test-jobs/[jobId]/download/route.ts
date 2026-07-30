import { NextRequest, NextResponse } from "next/server";
import { TEST_RUNS_BUCKET, getSupabaseAdmin } from "@/lib/supabase-admin";
import { jsonError, requireSession } from "@/app/api/test-jobs/_utils";

type RouteContext = { params: Promise<{ jobId: string }> };

export async function GET(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;
  const { jobId } = await context.params;
  const filename = request.nextUrl.searchParams.get("filename") || "teste.json";

  try {
    const supabase = getSupabaseAdmin();
    const { data: job, error } = await supabase
      .from("test_jobs")
      .select("id, status, final_storage_path")
      .eq("id", jobId)
      .maybeSingle();
    if (error) return jsonError(error.message, 500);
    if (!job) return jsonError("Job nao encontrado.", 404);
    if (!job.final_storage_path) {
      return jsonError("JSON ainda nao disponivel.", 409);
    }

    const { data: file, error: downloadError } = await supabase.storage
      .from(TEST_RUNS_BUCKET)
      .download(job.final_storage_path);
    if (downloadError || !file) {
      return jsonError(downloadError?.message || "Falha ao baixar JSON.", 502);
    }

    const buffer = await file.arrayBuffer();
    return new NextResponse(buffer, {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Content-Disposition": `attachment; filename="${filename}"`,
      },
    });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha no download.", 500);
  }
}
