/**
 * OpenAI vision helpers for test-run Edge Functions.
 */

export async function askVisionJson(options: {
  prompt: string;
  imageUrl: string;
  model: string;
  maxTokens?: number;
  jsonSchema?: Record<string, unknown>;
  corrective?: boolean;
}): Promise<{ data: Record<string, unknown>; responseId?: string }> {
  const apiKey = Deno.env.get("OPENAI_API_KEY");
  if (!apiKey) throw new Error("OPENAI_API_KEY nao configurada.");

  const prompt = options.corrective
    ? `${options.prompt}\n\nIMPORTANTE: Retorne APENAS JSON valido com a raiz obrigatoria { "tipo_pagina", "pagina", "conteudo": [] }. Nao invente campos fora do contrato.`
    : options.prompt;

  const body: Record<string, unknown> = {
    model: options.model,
    input: [
      {
        role: "user",
        content: [
          { type: "input_text", text: prompt },
          { type: "input_image", image_url: options.imageUrl },
        ],
      },
    ],
  };

  if (options.maxTokens && options.maxTokens > 0) {
    body.max_output_tokens = options.maxTokens;
  }

  if (options.jsonSchema) {
    body.text = {
      format: {
        type: "json_schema",
        name: options.jsonSchema.name ?? "linearizacao_pagina",
        strict: false,
        schema: options.jsonSchema.schema ?? options.jsonSchema,
      },
    };
  } else {
    body.text = { format: { type: "json_object" } };
  }

  const response = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`OpenAI ${response.status}: ${JSON.stringify(payload).slice(0, 400)}`);
  }

  const text = extractOutputText(payload);
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(text) as Record<string, unknown>;
  } catch {
    const match = text.match(/\{[\s\S]*\}/);
    if (!match) throw new Error(`OpenAI nao retornou JSON: ${text.slice(0, 300)}`);
    data = JSON.parse(match[0]) as Record<string, unknown>;
  }

  return { data, responseId: typeof payload.id === "string" ? payload.id : undefined };
}

export async function askVisionText(options: {
  prompt: string;
  imageUrl: string;
  model: string;
  maxTokens?: number;
}): Promise<string> {
  const apiKey = Deno.env.get("OPENAI_API_KEY");
  if (!apiKey) throw new Error("OPENAI_API_KEY nao configurada.");

  const body: Record<string, unknown> = {
    model: options.model,
    input: [
      {
        role: "user",
        content: [
          { type: "input_text", text: options.prompt },
          { type: "input_image", image_url: options.imageUrl },
        ],
      },
    ],
    max_output_tokens: options.maxTokens ?? 32,
  };

  const response = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`OpenAI ${response.status}: ${JSON.stringify(payload).slice(0, 400)}`);
  }
  return extractOutputText(payload).trim();
}

function extractOutputText(payload: Record<string, unknown>): string {
  if (typeof payload.output_text === "string" && payload.output_text.trim()) {
    return payload.output_text;
  }
  const output = payload.output;
  if (!Array.isArray(output)) return "";
  const chunks: string[] = [];
  for (const item of output) {
    if (!item || typeof item !== "object") continue;
    const content = (item as { content?: unknown }).content;
    if (!Array.isArray(content)) continue;
    for (const part of content) {
      if (!part || typeof part !== "object") continue;
      const text = (part as { text?: unknown }).text;
      if (typeof text === "string") chunks.push(text);
    }
  }
  return chunks.join("\n").trim();
}
