import { NextRequest, NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabase-admin";
import { jsonError, requireSession } from "@/app/api/test-jobs/_utils";

type RouteContext = { params: Promise<{ jobId: string }> };

type ManifestPage = {
  page_number: number;
  page_storage_path: string;
  width_px?: number;
  height_px?: number;
  figures?: Array<{
    figure_key: string;
    figure_index: number;
    storage_path: string;
    width_px?: number;
    height_px?: number;
    bbox?: Record<string, number>;
  }>;
};

export async function POST(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;
  const { jobId } = await context.params;

  try {
    const body = (await request.json()) as { pages?: ManifestPage[] };
    if (!body.pages?.length) return jsonError("Manifesto sem paginas.", 400);

    const supabase = getSupabaseAdmin();
    const { data: job, error: jobError } = await supabase
      .from("test_jobs")
      .select("id, status")
      .eq("id", jobId)
      .maybeSingle();
    if (jobError) return jsonError(jobError.message, 500);
    if (!job) return jsonError("Job nao encontrado.", 404);
    if (job.status !== "uploading") return jsonError("Job nao esta em upload.", 409);

    const pageRows = body.pages.map((page) => ({
      job_id: jobId,
      page_number: page.page_number,
      status: "pending",
      page_storage_path: page.page_storage_path,
      width_px: page.width_px ?? null,
      height_px: page.height_px ?? null,
    }));

    const { data: insertedPages, error: pagesError } = await supabase
      .from("test_pages")
      .upsert(pageRows, { onConflict: "job_id,page_number" })
      .select("id, page_number");
    if (pagesError || !insertedPages) {
      return jsonError(pagesError?.message || "Falha ao inserir paginas.", 500);
    }

    const pageIdByNumber = new Map(insertedPages.map((row) => [row.page_number, row.id]));
    const figureRows: Array<Record<string, unknown>> = [];
    for (const page of body.pages) {
      const pageId = pageIdByNumber.get(page.page_number);
      if (!pageId) continue;
      for (const figure of page.figures ?? []) {
        figureRows.push({
          job_id: jobId,
          page_id: pageId,
          page_number: page.page_number,
          figure_key: figure.figure_key,
          figure_index: figure.figure_index,
          status: "pending",
          storage_path: figure.storage_path,
          width_px: figure.width_px ?? null,
          height_px: figure.height_px ?? null,
          bbox: figure.bbox ?? null,
        });
      }
    }

    if (figureRows.length) {
      const { error: figuresError } = await supabase
        .from("test_figures")
        .upsert(figureRows, { onConflict: "job_id,figure_key" });
      if (figuresError) return jsonError(figuresError.message, 500);
    }

    const { error: updateError } = await supabase
      .from("test_jobs")
      .update({
        total_pages: body.pages.length,
        total_figures: figureRows.length,
      })
      .eq("id", jobId);
    if (updateError) return jsonError(updateError.message, 500);

    return NextResponse.json({ ok: true, pages: body.pages.length, figures: figureRows.length });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha ao registrar manifesto.", 500);
  }
}
