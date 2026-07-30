import { NextRequest, NextResponse } from "next/server";
import { TEST_RUNS_BUCKET, getSupabaseAdmin } from "@/lib/supabase-admin";
import { jsonError, requireSession } from "@/app/api/test-jobs/_utils";

type RouteContext = { params: Promise<{ jobId: string }> };

export async function POST(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;
  const { jobId } = await context.params;

  try {
    const body = (await request.json()) as {
      paths?: Array<{ path: string; contentType?: string }>;
    };
    if (!body.paths?.length) return jsonError("Lista de paths vazia.", 400);

    const supabase = getSupabaseAdmin();
    const { data: job, error: jobError } = await supabase
      .from("test_jobs")
      .select("id, status")
      .eq("id", jobId)
      .maybeSingle();
    if (jobError) return jsonError(jobError.message, 500);
    if (!job) return jsonError("Job nao encontrado.", 404);
    if (job.status !== "uploading") {
      return jsonError("Job nao esta em estado de upload.", 409);
    }

    const uploads: Array<{ path: string; token: string; signedUrl: string }> = [];
    for (const item of body.paths) {
      if (!item.path.startsWith(`${jobId}/`)) {
        return jsonError(`Path fora do prefixo do job: ${item.path}`, 400);
      }
      const { data, error } = await supabase.storage
        .from(TEST_RUNS_BUCKET)
        .createSignedUploadUrl(item.path);
      if (error || !data) {
        return jsonError(error?.message || `Falha ao assinar ${item.path}`, 500);
      }
      uploads.push({
        path: item.path,
        token: data.token,
        signedUrl: data.signedUrl,
      });
    }

    return NextResponse.json({ uploads });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha ao assinar uploads.", 500);
  }
}
