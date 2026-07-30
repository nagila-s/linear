import crypto from "node:crypto";
import type { PromptSnapshot } from "@/lib/prompt-router";
import { sanitizePromptOverrides } from "@/lib/prompt-router";

export function sha256Hex(input: string | Buffer): string {
  return crypto.createHash("sha256").update(input).digest("hex");
}

export type PromptHashMap = Record<string, string>;

export function hashPromptSnapshot(raw: unknown): {
  snapshot: PromptSnapshot;
  hashes: PromptHashMap;
  globalHash: string;
} {
  const snapshot = sanitizePromptOverrides(raw);
  const hashes: PromptHashMap = {};
  const orderedKeys = Object.keys(snapshot).sort((a, b) => a.localeCompare(b));
  for (const key of orderedKeys) {
    hashes[key] = sha256Hex(snapshot[key] ?? "");
  }
  const globalHash = sha256Hex(
    orderedKeys.map((key) => `${key}:${hashes[key]}`).join("|"),
  );
  return { snapshot, hashes, globalHash };
}

/** Raiz obrigatória do JSON de linearização (base.txt). */
export function validateLinearizationRoot(data: unknown): {
  ok: boolean;
  error?: string;
} {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return { ok: false, error: "Resposta nao e um objeto JSON." };
  }
  const obj = data as Record<string, unknown>;
  if (typeof obj.tipo_pagina !== "string" || !obj.tipo_pagina.trim()) {
    return { ok: false, error: 'Campo obrigatorio ausente: "tipo_pagina".' };
  }
  if (!("pagina" in obj)) {
    return { ok: false, error: 'Campo obrigatorio ausente: "pagina".' };
  }
  if (!Array.isArray(obj.conteudo)) {
    return { ok: false, error: 'Campo obrigatorio ausente ou invalido: "conteudo" (array).' };
  }
  return { ok: true };
}

export const LINEARIZATION_JSON_SCHEMA = {
  name: "linearizacao_pagina",
  strict: true,
  schema: {
    type: "object",
    additionalProperties: true,
    required: ["tipo_pagina", "pagina", "conteudo"],
    properties: {
      tipo_pagina: { type: "string" },
      pagina: {
        anyOf: [{ type: "integer" }, { type: "string" }],
      },
      conteudo: {
        type: "array",
        items: { type: "object", additionalProperties: true },
      },
    },
  },
} as const;
