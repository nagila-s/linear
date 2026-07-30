export async function describeWithDorina(options: {
  imageUrl: string;
  context: string;
}): Promise<Record<string, unknown>> {
  const url = Deno.env.get("DORINA_API_URL");
  const key = Deno.env.get("DORINA_API_KEY");
  const header = (Deno.env.get("DORINA_API_KEY_HEADER") || "Authorization").trim();
  if (!url || !key) {
    throw new Error("DORINA_API_URL / DORINA_API_KEY nao configuradas.");
  }

  const scope =
    "Descreva APENAS o que está visível na imagem enviada (a figura/ilustração em si). " +
    "Ignore texto de parágrafo ou número de página ao redor do recorte.";
  const context = options.context?.trim()
    ? `${options.context.trim()}\n\n${scope}`
    : scope;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      [header]: key,
      accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      data: {
        imageId: 0,
        documentId: 0,
        url: options.imageUrl,
        braille: (Deno.env.get("DORINA_BRAILLE") || "false") === "true",
        documentType: Deno.env.get("DORINA_DOCUMENT_TYPE") || "string",
        context,
      },
    }),
  });

  const raw = await response.text();
  if (!response.ok) {
    throw new Error(`Dorina ${response.status}: ${raw.slice(0, 400)}`);
  }
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    throw new Error(`Dorina JSON invalido: ${raw.slice(0, 300)}`);
  }
  if (data.error) throw new Error(`Dorina error: ${String(data.error).slice(0, 400)}`);
  const description = String(data.description || data.texto || data.caption || "").trim();
  data.description = description;
  return data;
}
