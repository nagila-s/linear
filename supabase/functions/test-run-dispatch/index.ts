import {
  archiveMessage,
  enqueue,
  getPromptFromSnapshot,
  getServiceClient,
  normalizePageType,
  readQueue,
  refreshCounters,
  sha256Hex,
  shouldClassify,
  signedUrl,
  TEST_RUNS_BUCKET,
  validateLinearizationRoot,
  type QueueMessage,
  type QueueRow,
} from "../_shared/test-run.ts";
import { askVisionJson, askVisionText } from "../_shared/openai.ts";
import { describeWithDorina } from "../_shared/dorina.ts";
import { omitImageCredits, stripImageCredits } from "../_shared/image-credits.ts";
import { mergeStylesIntoPage, pagesFromPayload } from "../_shared/style-merge.ts";
import {
  analyzeTextGaps,
  buildGapFillPrompt,
  editorialCharCount,
  preservesClassification,
} from "../_shared/text-gap-fill.ts";

const LINEARIZATION_SCHEMA = {
  name: "linearizacao_pagina",
  schema: {
    type: "object",
    additionalProperties: true,
    required: ["tipo_pagina", "pagina", "conteudo"],
    properties: {
      tipo_pagina: { type: "string" },
      pagina: {},
      conteudo: { type: "array", items: { type: "object", additionalProperties: true } },
    },
  },
};

/** Limite de reinvocacoes encadeadas, para uma fila envenenada nao rodar para sempre. */
const MAX_CHAIN_DEPTH = 60;

/**
 * Reinvoca a propria funcao quando a fila nao terminou, para o job seguir andando
 * mesmo que ninguem esteja com a area de testes aberta no navegador.
 */
function chainNextRun(depth: number): void {
  const baseUrl = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!baseUrl || !key || depth >= MAX_CHAIN_DEPTH) return;

  const pending = fetch(`${baseUrl}/functions/v1/test-run-dispatch`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ depth: depth + 1 }),
  }).catch(() => undefined);

  const runtime = (globalThis as { EdgeRuntime?: { waitUntil: (p: Promise<unknown>) => void } })
    .EdgeRuntime;
  if (runtime?.waitUntil) {
    runtime.waitUntil(pending);
  }
}

Deno.serve(async (req) => {
  try {
    if (req.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    let depth = 0;
    try {
      const body = (await req.json()) as { depth?: number } | null;
      if (body && typeof body.depth === "number") depth = body.depth;
    } catch {
      // corpo vazio ou invalido: trata como primeira invocacao
    }

    const supabase = getServiceClient();
    const results: Array<Record<string, unknown>> = [];
    const startedAt = Date.now();
    // Drena a fila enquanto sobrar tempo de execucao, em vez de um unico lote:
    // uma invocacao por lote deixaria o job parado esperando o proximo disparo.
    const budgetMs = 100_000;
    let drained = false;

    while (Date.now() - startedAt < budgetMs) {
      const rows = await readQueue(supabase, 180, 5);
      if (!rows.length) {
        drained = true;
        break;
      }

      for (const row of rows) {
        try {
          await processMessage(supabase, row);
          await archiveMessage(supabase, row.msg_id);
          results.push({ msg_id: row.msg_id, ok: true, kind: row.message?.kind });
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          results.push({ msg_id: row.msg_id, ok: false, error: message });
          // Visibility timeout reentrega automaticamente; se estourou tentativas, marca falha.
          await handleFailure(supabase, row, message);
        }
      }
    }

    if (!drained && results.length) {
      chainNextRun(depth);
    }

    return Response.json({ processed: results.length, drained, depth, results });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
});

async function processMessage(
  supabase: ReturnType<typeof getServiceClient>,
  row: QueueRow,
): Promise<void> {
  const msg = row.message;
  if (!msg?.kind || !msg.job_id) throw new Error("Mensagem invalida.");

  switch (msg.kind) {
    case "classify_page":
      await classifyPage(supabase, msg);
      break;
    case "linearize_page":
      await linearizePage(supabase, msg);
      break;
    case "describe_figure":
      await describeFigure(supabase, msg);
      break;
    case "finalize":
      await finalizeJob(supabase, msg.job_id);
      break;
    default:
      throw new Error(`Kind desconhecido: ${(msg as QueueMessage).kind}`);
  }
}

async function classifyPage(
  supabase: ReturnType<typeof getServiceClient>,
  msg: QueueMessage,
): Promise<void> {
  const pageId = msg.page_id!;
  const { data: page, error } = await supabase.from("test_pages").select("*").eq("id", pageId).single();
  if (error || !page) throw new Error(error?.message || "Pagina nao encontrada.");
  if (page.status === "ok") {
    await maybeEnqueueFinalize(supabase, msg.job_id);
    return;
  }

  const { data: job, error: jobError } = await supabase
    .from("test_jobs")
    .select("*")
    .eq("id", msg.job_id)
    .single();
  if (jobError || !job) throw new Error(jobError?.message || "Job nao encontrado.");

  await supabase
    .from("test_pages")
    .update({ status: "running", attempts: (page.attempts || 0) + 1 })
    .eq("id", pageId);
  await supabase.from("test_jobs").update({ status: "running" }).eq("id", msg.job_id);

  let pageType = "conteudo";
  if (!job.miolo_only && shouldClassify(page.page_number, job.total_pages)) {
    const snapshot = (job.prompt_snapshot || {}) as Record<string, string>;
    const classifier = (snapshot["classificador.txt"] || "").trim();
    if (!classifier) throw new Error("Prompt ausente no snapshot: classificador.txt");
    const imageUrl = await signedUrl(supabase, page.page_storage_path);
    const model = Deno.env.get("OPENAI_MODEL_CLASSIFIER") || "gpt-4.1-mini";
    const raw = await askVisionText({
      prompt: classifier,
      imageUrl,
      model,
      maxTokens: 16,
    });
    pageType = normalizePageType(raw);
  }

  await supabase.from("test_pages").update({ page_type: pageType }).eq("id", pageId);
  await enqueue(supabase, {
    kind: "linearize_page",
    job_id: msg.job_id,
    page_id: pageId,
    page_number: page.page_number,
  });
}

async function linearizePage(
  supabase: ReturnType<typeof getServiceClient>,
  msg: QueueMessage,
): Promise<void> {
  const pageId = msg.page_id!;
  const { data: page, error } = await supabase.from("test_pages").select("*").eq("id", pageId).single();
  if (error || !page) throw new Error(error?.message || "Pagina nao encontrada.");
  if (page.status === "ok" && page.content) {
    await enqueueFiguresOrFinalize(supabase, msg.job_id, page);
    return;
  }

  const { data: job, error: jobError } = await supabase
    .from("test_jobs")
    .select("*")
    .eq("id", msg.job_id)
    .single();
  if (jobError || !job) throw new Error(jobError?.message || "Job nao encontrado.");

  const snapshot = (job.prompt_snapshot || {}) as Record<string, string>;
  const pageType = page.page_type || "conteudo";
  const { prompt, promptFile } = getPromptFromSnapshot(snapshot, pageType);
  const promptHash = await sha256Hex(prompt);
  const imageUrl = await signedUrl(supabase, page.page_storage_path);
  const model = Deno.env.get("OPENAI_MODEL_LINEARIZATION") || "gpt-5.2";

  await supabase
    .from("test_pages")
    .update({
      status: "running",
      prompt_file: promptFile,
      prompt_hash: promptHash,
      openai_model: model,
      attempts: (page.attempts || 0) + 1,
    })
    .eq("id", pageId);

  let result = await askVisionJson({
    prompt,
    imageUrl,
    model,
    jsonSchema: LINEARIZATION_SCHEMA,
  });
  let validation = validateLinearizationRoot(result.data);
  if (!validation.ok) {
    result = await askVisionJson({
      prompt,
      imageUrl,
      model,
      jsonSchema: LINEARIZATION_SCHEMA,
      corrective: true,
    });
    validation = validateLinearizationRoot(result.data);
    if (!validation.ok) {
      throw new Error(validation.error || "JSON fora do contrato.");
    }
  }

  const content = {
    ...result.data,
    tipo_pagina: pageType,
    prompt_version: "test",
    prompt_file: promptFile,
    prompt_hash: promptHash,
  };

  const filled = omitImageCredits(
    await fillTextGapsIfNeeded(supabase, msg.job_id, page.page_number, imageUrl, content),
  ) as Record<string, unknown>;

  await supabase
    .from("test_pages")
    .update({
      status: "ok",
      content: filled,
      openai_response_id: result.responseId ?? null,
      error_message: null,
    })
    .eq("id", pageId);

  await enqueueFiguresOrFinalize(supabase, msg.job_id, { ...page, page_type: pageType, content: filled });
  await refreshCounters(supabase, msg.job_id);
}

async function loadPagePlainText(
  supabase: ReturnType<typeof getServiceClient>,
  jobId: string,
  pageNumber: number,
): Promise<string> {
  try {
    const { data, error } = await supabase.storage
      .from(TEST_RUNS_BUCKET)
      .download(`${jobId}/text_spans.json`);
    if (error || !data) return "";
    const payload = JSON.parse(await data.text()) as {
      pages?: Array<{ page_number: number; runs?: Array<{ text?: string }> }>;
    };
    const byPage = pagesFromPayload(payload);
    const styles = byPage.get(pageNumber);
    if (!styles) return "";
    return stripImageCredits(styles.runs.map((run) => run.text).join(""));
  } catch {
    return "";
  }
}

async function fillTextGapsIfNeeded(
  supabase: ReturnType<typeof getServiceClient>,
  jobId: string,
  pageNumber: number,
  imageUrl: string,
  content: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const enabled = (Deno.env.get("TEXT_GAP_FILL_ENABLED") || "true").toLowerCase() !== "false";
  if (!enabled) return content;

  const plain = await loadPagePlainText(supabase, jobId, pageNumber);
  const report = analyzeTextGaps(content, plain);
  if (!report.needsFill) return content;

  const model = Deno.env.get("OPENAI_MODEL_CLASSIFIER") || "gpt-4.1-mini";
  const maxTokens = Number(Deno.env.get("TEXT_GAP_FILL_MAX_OUTPUT_TOKENS") || 16384);
  try {
    const patched = await askVisionJson({
      prompt: buildGapFillPrompt(content, plain, report.missingSpans),
      imageUrl,
      model,
      maxTokens: Number.isFinite(maxTokens) && maxTokens > 0 ? maxTokens : 16384,
      jsonSchema: LINEARIZATION_SCHEMA,
    });
    const data = patched.data;
    if (!data || typeof data !== "object") return content;
    if (!preservesClassification(content, data)) return content;
    if (editorialCharCount(data) < editorialCharCount(content)) return content;
    return {
      ...data,
      tipo_pagina: content.tipo_pagina,
      prompt_version: content.prompt_version,
      prompt_file: content.prompt_file,
      prompt_hash: content.prompt_hash,
    };
  } catch {
    return content;
  }
}

async function enqueueFiguresOrFinalize(
  supabase: ReturnType<typeof getServiceClient>,
  jobId: string,
  page: { id: string; page_number: number; page_type?: string | null; content?: Record<string, unknown> | null },
): Promise<void> {
  const pageType = page.page_type || "conteudo";
  const skipFigures = pageType !== "conteudo";

  const { data: figures } = await supabase
    .from("test_figures")
    .select("*")
    .eq("page_id", page.id)
    .order("figure_index");

  if (skipFigures || !figures?.length) {
    if (figures?.length) {
      await supabase
        .from("test_figures")
        .update({ status: "skipped" })
        .eq("page_id", page.id)
        .in("status", ["pending", "queued", "failed"]);
    }
    await maybeEnqueueFinalize(supabase, jobId);
    return;
  }

  // Extrai legendas/contexto simples do content se houver blocos imagem
  const contexts = extractFigureContexts(page.content);

  for (const figure of figures) {
    if (figure.status === "ok") continue;
    await supabase
      .from("test_figures")
      .update({
        status: "queued",
        context: contexts[figure.figure_key] || figure.context || "",
      })
      .eq("id", figure.id);
    await enqueue(supabase, {
      kind: "describe_figure",
      job_id: jobId,
      page_id: page.id,
      page_number: page.page_number,
      figure_id: figure.id,
      figure_key: figure.figure_key,
    });
  }
}

function extractFigureContexts(content: Record<string, unknown> | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!content || !Array.isArray(content.conteudo)) return out;
  for (const block of content.conteudo) {
    if (!block || typeof block !== "object") continue;
    const item = block as Record<string, unknown>;
    if (String(item.tipo || "") !== "imagem") continue;
    const key = String(item.figure_key || item.id || "").trim();
    if (!key) continue;
    const legend = String(item.legenda || item.texto || item.caption || "").trim();
    out[key] = legend;
  }
  return out;
}

async function describeFigure(
  supabase: ReturnType<typeof getServiceClient>,
  msg: QueueMessage,
): Promise<void> {
  const figureId = msg.figure_id!;
  const { data: figure, error } = await supabase.from("test_figures").select("*").eq("id", figureId).single();
  if (error || !figure) throw new Error(error?.message || "Figura nao encontrada.");
  if (figure.status === "ok") {
    await maybeEnqueueFinalize(supabase, msg.job_id);
    return;
  }

  await supabase
    .from("test_figures")
    .update({ status: "running", attempts: (figure.attempts || 0) + 1 })
    .eq("id", figureId);

  const imageUrl = await signedUrl(supabase, figure.storage_path, 600);
  const payload = await describeWithDorina({
    imageUrl,
    context: figure.context || "",
  });
  const description = String(payload.description || "").trim();
  if (!description) throw new Error("Dorina retornou descricao vazia.");

  await supabase
    .from("test_figures")
    .update({
      status: "ok",
      description,
      dorina_payload: payload,
      error_message: null,
    })
    .eq("id", figureId);

  await applyDescriptionToPage(supabase, figure.page_id, figure.figure_key, description);
  await refreshCounters(supabase, msg.job_id);
  await maybeEnqueueFinalize(supabase, msg.job_id);
}

async function applyDescriptionToPage(
  supabase: ReturnType<typeof getServiceClient>,
  pageId: string,
  figureKey: string,
  description: string,
): Promise<void> {
  const { data: page } = await supabase.from("test_pages").select("content").eq("id", pageId).maybeSingle();
  if (!page?.content || typeof page.content !== "object") return;
  const content = { ...(page.content as Record<string, unknown>) };
  if (!Array.isArray(content.conteudo)) return;
  content.conteudo = content.conteudo.map((block) => {
    if (!block || typeof block !== "object") return block;
    const item = { ...(block as Record<string, unknown>) };
    const key = String(item.figure_key || item.id || "").trim();
    if (key === figureKey || key === `fig${figureKey.replace(/^fig/i, "")}`) {
      item.descricao = description;
      item.description = description;
    }
    return item;
  });
  await supabase.from("test_pages").update({ content }).eq("id", pageId);
}

async function maybeEnqueueFinalize(
  supabase: ReturnType<typeof getServiceClient>,
  jobId: string,
): Promise<void> {
  const { count: pendingPages } = await supabase
    .from("test_pages")
    .select("id", { count: "exact", head: true })
    .eq("job_id", jobId)
    .in("status", ["pending", "queued", "running"]);

  const { count: pendingFigures } = await supabase
    .from("test_figures")
    .select("id", { count: "exact", head: true })
    .eq("job_id", jobId)
    .in("status", ["pending", "queued", "running"]);

  if ((pendingPages || 0) > 0 || (pendingFigures || 0) > 0) return;

  await enqueue(supabase, { kind: "finalize", job_id: jobId });
}

async function finalizeJob(
  supabase: ReturnType<typeof getServiceClient>,
  jobId: string,
): Promise<void> {
  const { data: job, error } = await supabase.from("test_jobs").select("*").eq("id", jobId).single();
  if (error || !job) throw new Error(error?.message || "Job nao encontrado.");

  const { data: pages } = await supabase
    .from("test_pages")
    .select("*")
    .eq("job_id", jobId)
    .order("page_number");
  const { data: figures } = await supabase
    .from("test_figures")
    .select("*")
    .eq("job_id", jobId)
    .order("page_number")
    .order("figure_index");

  const promptHashes =
    ((job.metadata as Record<string, unknown> | null)?.prompt_hashes as Record<string, string>) || {};

  // Merge tipográfico a partir de text_spans.json (extraído no browser via PDF.js).
  let textSpansByPage = pagesFromPayload(null);
  try {
    const { data: spansBlob, error: spansError } = await supabase.storage
      .from(TEST_RUNS_BUCKET)
      .download(`${jobId}/text_spans.json`);
    if (!spansError && spansBlob) {
      const spansJson = JSON.parse(await spansBlob.text());
      textSpansByPage = pagesFromPayload(spansJson);
    }
  } catch {
    // Sem spans: final.json sai sem merge (PDF escaneado / upload antigo).
  }

  const mergedPages = (pages || []).map((page) => {
    const content = page.content;
    const styles = textSpansByPage.get(page.page_number);
    let mergedContent = content;
    if (content && typeof content === "object" && !Array.isArray(content) && styles) {
      mergedContent = omitImageCredits(
        mergeStylesIntoPage(content as Record<string, unknown>, styles),
      );
    }
    return {
      page_number: page.page_number,
      status: page.status,
      content: mergedContent,
      prompt_file: page.prompt_file,
      prompt_hash: page.prompt_hash,
      openai_model: page.openai_model,
      openai_response_id: page.openai_response_id,
      page_type: page.page_type,
    };
  });

  const finalPayload = {
    isbn: job.isbn,
    job_id: job.id,
    job_type: "linearizar",
    test_run: true,
    prompt_version: "test",
    process_version: `test-${job.id.slice(0, 8)}`,
    dpi: job.dpi,
    miolo_only: job.miolo_only,
    prompt_hash: job.prompt_hash,
    prompt_hashes: promptHashes,
    prompt_files: Object.keys(job.prompt_snapshot || {}).sort(),
    pages: mergedPages,
    image_context: (figures || [])
      .filter((f) => f.context)
      .map((f) => ({ figure_key: f.figure_key, context: f.context })),
    descriptions: (figures || []).map((f) => ({
      figure_key: f.figure_key,
      page_number: f.page_number,
      status: f.status,
      description: f.description,
      context: f.context,
      prompt_version: "test",
    })),
    stats: {
      pages: job.total_pages,
      figures: job.total_figures,
      described_ok: (figures || []).filter((f) => f.status === "ok").length,
      dorina_failed: (figures || []).filter((f) => f.status === "failed").length,
      pages_failed: (pages || []).filter((p) => p.status === "failed").length,
    },
  };

  const path = `${jobId}/final.json`;
  const bytes = new TextEncoder().encode(JSON.stringify(finalPayload, null, 2));
  const { error: uploadError } = await supabase.storage
    .from(TEST_RUNS_BUCKET)
    .upload(path, bytes, { contentType: "application/json", upsert: true });
  if (uploadError) throw new Error(uploadError.message);

  await refreshCounters(supabase, jobId);
  await supabase
    .from("test_jobs")
    .update({
      final_storage_path: path,
      finished_at: new Date().toISOString(),
    })
    .eq("id", jobId);
}

async function handleFailure(
  supabase: ReturnType<typeof getServiceClient>,
  row: QueueRow,
  message: string,
): Promise<void> {
  const msg = row.message;
  if (!msg) return;

  if (msg.kind === "classify_page" || msg.kind === "linearize_page") {
    if (!msg.page_id) return;
    const { data: page } = await supabase
      .from("test_pages")
      .select("attempts, max_attempts")
      .eq("id", msg.page_id)
      .maybeSingle();
    if (page && page.attempts >= page.max_attempts) {
      await supabase
        .from("test_pages")
        .update({ status: "failed", error_message: message.slice(0, 1000) })
        .eq("id", msg.page_id);
      await archiveMessage(supabase, row.msg_id);
      await refreshCounters(supabase, msg.job_id);
      await maybeEnqueueFinalize(supabase, msg.job_id);
    }
  }

  if (msg.kind === "describe_figure" && msg.figure_id) {
    const { data: figure } = await supabase
      .from("test_figures")
      .select("attempts, max_attempts")
      .eq("id", msg.figure_id)
      .maybeSingle();
    if (figure && figure.attempts >= figure.max_attempts) {
      await supabase
        .from("test_figures")
        .update({ status: "failed", error_message: message.slice(0, 1000) })
        .eq("id", msg.figure_id);
      await archiveMessage(supabase, row.msg_id);
      await refreshCounters(supabase, msg.job_id);
      await maybeEnqueueFinalize(supabase, msg.job_id);
    }
  }
}
