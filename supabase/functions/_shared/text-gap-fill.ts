/**
 * Detecta texto do PDF ausente no JSON e valida patch sem mudar a classificação.
 * Espelha src/pipeline/steps/text_gap_fill.py
 */

import { isImageCredit, stripImageCredits } from "./image-credits.ts";

const TEXT_KEYS = new Set([
  "texto",
  "trecho",
  "instrucao",
  "enunciado",
  "titulo",
  "titulo_quadro",
  "titulo_boxe",
  "titulo_tabela",
  "cabecalho",
]);

const SKIP_KEYS = new Set([
  "tipo",
  "tipo_pagina",
  "pagina",
  "prompt_version",
  "estilo",
  "letra",
  "marcador",
  "numero",
  "descricao",
  "figure_key",
]);

const MIN_PDF_CHARS = 80;
const MIN_SPAN_CHARS = 16;
const MIN_TOTAL_MISSING = 40;
const MAX_SNIPPETS = 24;
const MAX_SNIPPET_CHARS = 500;
const MAX_PDF_IN_PROMPT = 12000;
const MAX_JSON_IN_PROMPT = 50000;
const NOISE_RE =
  /(shutterstock|getty\s*images|alamy|istock|acervo\s+da\s+editora|acervo\s+pessoal|reprodu[cç][aã]o)/i;
const PAGE_NUM_RE = /^[\d\s.\-/]+$/;

export type TextGapReport = {
  pdfChars: number;
  jsonChars: number;
  missingSpans: string[];
  missingChars: number;
  needsFill: boolean;
};

export function collapseForDiff(text: string): string {
  return (text || "").replace(/\u00ad/g, "").replace(/\s+/g, " ").trim();
}

function isNoiseSpan(text: string): boolean {
  const raw = (text || "").trim();
  if (raw.length < MIN_SPAN_CHARS) return true;
  if (PAGE_NUM_RE.test(raw)) return true;
  if (isImageCredit(raw)) return true;
  if (NOISE_RE.test(raw) && raw.length < 80) return true;
  let letters = 0;
  for (const ch of raw) {
    if (/\p{L}/u.test(ch)) letters += 1;
  }
  return letters < 8;
}

export function editorialPlainText(node: unknown): string {
  const parts: string[] = [];

  const walk = (n: unknown): void => {
    if (Array.isArray(n)) {
      for (const item of n) walk(item);
      return;
    }
    if (!n || typeof n !== "object") return;
    const obj = n as Record<string, unknown>;
    for (const [key, value] of Object.entries(obj)) {
      if (SKIP_KEYS.has(key)) continue;
      if (TEXT_KEYS.has(key)) {
        if (typeof value === "string" && value.trim()) {
          parts.push(value);
        } else if (Array.isArray(value)) {
          for (const item of value) {
            if (item && typeof item === "object") {
              const rec = item as Record<string, unknown>;
              const trecho = String(rec.trecho || rec.texto || "").trim();
              if (trecho) parts.push(trecho);
              walk(rec);
            } else if (typeof item === "string" && item.trim()) {
              parts.push(item);
            }
          }
        }
        continue;
      }
      if (typeof value === "string") {
        if (value.length >= 8) parts.push(value);
        continue;
      }
      walk(value);
    }
  };

  walk(node);
  return parts.join("\n");
}

export function editorialCharCount(node: unknown): number {
  return editorialPlainText(node).length;
}

function findMissingPdfSpans(pdfText: string, jsonText: string): string[] {
  const pdf = collapseForDiff(pdfText);
  const json = collapseForDiff(jsonText).toLocaleLowerCase();
  if (!pdf) return [];
  if (!json) {
    const span = pdf.trim();
    return isNoiseSpan(span) ? [] : [span.slice(0, MAX_SNIPPET_CHARS)];
  }

  const words = pdf.split(" ").filter(Boolean);
  const missing: string[] = [];
  let buf: string[] = [];

  const flush = () => {
    const chunk = buf.join(" ").trim();
    buf = [];
    if (!chunk || isNoiseSpan(chunk)) return;
    if (json.includes(chunk.toLocaleLowerCase())) return;
    missing.push(chunk.slice(0, MAX_SNIPPET_CHARS));
  };

  let i = 0;
  while (i < words.length && missing.length < MAX_SNIPPETS) {
    const n = Math.min(6, words.length - i);
    const probe = words.slice(i, i + n).join(" ");
    if (n >= 3 && json.includes(probe.toLocaleLowerCase())) {
      flush();
      i += n;
      continue;
    }
    buf.push(words[i]);
    i += 1;
  }
  flush();
  return missing;
}

export function analyzeTextGaps(
  pageStructure: Record<string, unknown> | null | undefined,
  pdfText: string,
): TextGapReport {
  const pdf = stripImageCredits(pdfText || "").trim();
  const jsonPlain = editorialPlainText(pageStructure || {});
  const missingSpans = findMissingPdfSpans(pdf, jsonPlain);
  const missingChars = missingSpans.reduce((acc, span) => acc + span.length, 0);
  return {
    pdfChars: pdf.length,
    jsonChars: jsonPlain.length,
    missingSpans,
    missingChars,
    needsFill:
      pdf.length >= MIN_PDF_CHARS &&
      (missingChars >= MIN_TOTAL_MISSING || missingSpans.some((span) => span.length >= 40)),
  };
}

export function collectTipoFingerprint(node: unknown): string[] {
  const out: string[] = [];
  const walk = (n: unknown): void => {
    if (Array.isArray(n)) {
      for (const item of n) walk(item);
      return;
    }
    if (!n || typeof n !== "object") return;
    const obj = n as Record<string, unknown>;
    const tipo = obj.tipo;
    if (typeof tipo === "string" && tipo.trim()) out.push(tipo.trim());
    for (const value of Object.values(obj)) walk(value);
  };
  walk(node);
  return out;
}

function isSubsequence(small: string[], big: string[]): boolean {
  if (!small.length) return true;
  let i = 0;
  for (const item of big) {
    if (item === small[i]) {
      i += 1;
      if (i >= small.length) return true;
    }
  }
  return false;
}

export function preservesClassification(
  original: Record<string, unknown>,
  patched: Record<string, unknown>,
): boolean {
  const origPage = String(original.tipo_pagina || "").trim();
  const newPage = String(patched.tipo_pagina || "").trim();
  if (origPage && newPage && origPage !== newPage) return false;
  const origTipos = collectTipoFingerprint(original);
  if (!origTipos.length) return true;
  return isSubsequence(origTipos, collectTipoFingerprint(patched));
}

export function buildGapFillPrompt(
  pageStructure: Record<string, unknown>,
  pdfText: string,
  missingSpans: string[],
): string {
  let jsonDump = JSON.stringify(pageStructure);
  if (jsonDump.length > MAX_JSON_IN_PROMPT) {
    jsonDump = `${jsonDump.slice(0, MAX_JSON_IN_PROMPT - 20)}\n...[json cortado]...`;
  }
  let pdf = collapseForDiff(pdfText);
  if (pdf.length > MAX_PDF_IN_PROMPT) {
    pdf = `${pdf.slice(0, MAX_PDF_IN_PROMPT - 20)} ...[texto cortado]...`;
  }
  const snippets =
    missingSpans.slice(0, MAX_SNIPPETS).map((span) => `- ${span}`).join("\n") ||
    "- (trechos não listados)";

  return (
    "Você corrige um JSON já linearizado de uma página de livro didático.\n" +
    "Há trechos do PDF que NÃO estão no JSON. Insira esse texto no local correto.\n\n" +
    "REGRAS ABSOLUTAS:\n" +
    '- NÃO altere o campo "tipo" de nenhum bloco já existente.\n' +
    "- NÃO reclassifique, não funda, não renomeie e não reordene os blocos atuais.\n" +
    "- NÃO invente títulos, explicações ou conteúdo que não esteja no PDF.\n" +
    "- Só complete ou insira o texto faltante. Novos blocos só se o trecho for um bloco distinto; " +
    "aí use o tipo adequado (paragrafo, titulo_3, item, etc.) sem mudar os tipos já presentes.\n" +
    '- Mantenha a ordem de leitura. Retorne o JSON COMPLETO da página (raiz com "tipo_pagina", "pagina", "conteudo").\n' +
    '- Use string simples em "texto". Não marque negrito/itálico.\n\n' +
    "Trechos do PDF ausentes no JSON:\n" +
    `${snippets}\n\n` +
    "Texto nativo do PDF:\n" +
    `${pdf}\n\n` +
    "JSON atual (preserve os tipos):\n" +
    `${jsonDump}\n`
  );
}
