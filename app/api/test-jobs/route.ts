import { NextRequest, NextResponse } from "next/server";
import { hashPromptSnapshot } from "@/lib/prompt-hash";
import { getSupabaseAdmin } from "@/lib/supabase-admin";
import { jsonError, requireSession } from "@/app/api/test-jobs/_utils";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;

  try {
    const body = (await request.json()) as {
      filename?: string;
      isbn?: string;
      miolo_only?: boolean;
      dpi?: number;
      total_pages?: number;
      total_figures?: number;
      prompt_overrides?: Record<string, string>;
    };

    if (!body.filename?.trim()) {
      return jsonError("Nome do arquivo PDF obrigatorio.", 400);
    }
    if (!body.total_pages || body.total_pages < 1) {
      return jsonError("total_pages invalido.", 400);
    }
    if (body.total_pages > 30) {
      return jsonError("Limite da area de testes: 30 paginas.", 400);
    }

    const { snapshot, hashes, globalHash } = hashPromptSnapshot(body.prompt_overrides ?? {});
    if (!Object.keys(snapshot).length) {
      return jsonError("Nenhum prompt valido no snapshot.", 400);
    }
    if (!snapshot["base.txt"] && !snapshot["classificador.txt"]) {
      return jsonError("Snapshot precisa incluir ao menos base.txt ou classificador.txt.", 400);
    }

    const isbn = (body.isbn || body.filename.replace(/\.pdf$/i, "") || "teste").trim().slice(0, 128);
    const supabase = getSupabaseAdmin();
    const { data, error } = await supabase
      .from("test_jobs")
      .insert({
        isbn,
        filename: body.filename.trim(),
        status: "uploading",
        miolo_only: Boolean(body.miolo_only),
        dpi: body.dpi && body.dpi > 0 ? body.dpi : 120,
        total_pages: body.total_pages,
        total_figures: body.total_figures ?? 0,
        prompt_snapshot: snapshot,
        prompt_hash: globalHash,
        metadata: {
          prompt_hashes: hashes,
          source: "area-testes",
          isolated_from_aws: true,
        },
      })
      .select("id")
      .single();

    if (error || !data) {
      return jsonError(error?.message || "Falha ao criar test_job.", 500);
    }

    return NextResponse.json({ jobId: data.id });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha ao criar job de teste.", 500);
  }
}
