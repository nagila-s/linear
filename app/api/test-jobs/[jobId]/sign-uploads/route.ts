import { NextRequest, NextResponse } from "next/server";
import { TEST_RUNS_BUCKET, getSupabaseAdmin } from "@/lib/supabase-admin";
import { jsonError, requireSession } from "@/app/api/test-jobs/_utils";

type RouteContext = { params: Promise<{ jobId: string }> };

export const maxDuration = 60;

export async function POST(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;
  const { jobId } = await context.params;

  try {
    const body = (await request.json()) as {
      paths?: Array<{ path: string; contentType?: string }>;
    };
    if (!body.paths?.length) return jsonError("Lista de paths vazia.", 400);
    if (body.paths.length > 500) return jsonError("Demasiados paths no manifesto.", 400);

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

    for (const item of body.paths) {
      if (!item.path.startsWith(`${jobId}/`)) {
        return jsonError(`Path fora do prefixo do job: ${item.path}`, 400);
      }
    }

    const uploads: Array<{ path: string; token: string; signedUrl: string }> = [];
    const concurrency = 8;
    for (let i = 0; i < body.paths.length; i += concurrency) {
      const batch = body.paths.slice(i, i + concurrency);
      const signed = await Promise.all(
        batch.map(async (item) => {
          const { data, error } = await supabase.storage
            .from(TEST_RUNS_BUCKET)
            .createSignedUploadUrl(item.path);
          if (error || !data) {
            throw new Error(error?.message || `Falha ao assinar ${item.path}`);
          }
          return {
            path: item.path,
            token: data.token,
            signedUrl: data.signedUrl,
          };
        }),
      );
      uploads.push(...signed);
    }

    return NextResponse.json({ uploads });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha ao assinar uploads.", 500);
  }
}
