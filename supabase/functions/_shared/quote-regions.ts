/**
 * Regiões entre aspas no texto nativo e reinserção no JSON editorial.
 * Espelha src/pipeline/steps/quote_regions.py
 */

import { editorialPlainText } from "./text-gap-fill.ts";

type TextRun = { text: string; estilo: string };
type PageTextStyles = { page_number: number; runs: TextRun[]; char_count: number };

const QUOTE_PAIRS: Record<string, string> = {
  "\u201c": "\u201d",
  "\u201e": "\u201c",
  "\u00ab": "\u00bb",
  '"': '"',
};
const QUOTE_CHARS = new Set([...Object.keys(QUOTE_PAIRS), ...Object.values(QUOTE_PAIRS)]);
const MIN_QUOTE_CHARS = 40;

export function collapseQuotes(text: string): string {
  let s = (text || "").replace(/\u00ad/g, "");
  let out = "";
  for (const ch of s) out += QUOTE_CHARS.has(ch) ? '"' : ch;
  return out.replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

export function extractQuoteRegions(text: string, minChars = MIN_QUOTE_CHARS): string[] {
  const raw = text || "";
  if (!raw) return [];
  const regions: string[] = [];
  const seen = new Set<string>();
  let i = 0;
  while (i < raw.length) {
    const closer = QUOTE_PAIRS[raw[i]];
    if (!closer) {
      i += 1;
      continue;
    }
    const j = raw.indexOf(closer, i + 1);
    if (j < 0) {
      i += 1;
      continue;
    }
    const inner = raw.slice(i + 1, j).trim();
    if (inner.replace(/\s+/g, " ").length >= minChars) {
      const region = raw.slice(i, j + 1).trim();
      const key = collapseQuotes(region);
      if (key && !seen.has(key)) {
        seen.add(key);
        regions.push(region);
      }
    }
    i = j + 1;
  }
  return regions;
}

export function extractQuoteRegionsFromRuns(runs: TextRun[], minChars = MIN_QUOTE_CHARS): string[] {
  return extractQuoteRegions(runs.map((r) => r.text).join(""), minChars);
}

function quoteRegionPresent(region: string, editorial: string): boolean {
  const needle = collapseQuotes(region);
  if (!needle) return true;
  const hay = collapseQuotes(editorial);
  if (hay.includes(needle)) return true;
  const inner = collapseQuotes(region.trim().replace(/^["“”«»]+|["“”«»]+$/g, ""));
  if (inner.length >= 24 && hay.includes(inner)) return true;
  const words = inner.split(" ").filter(Boolean);
  if (words.length >= 8) {
    const probe = words.slice(0, 8).join(" ");
    if (hay.includes(probe)) return true;
  }
  return false;
}

// Citação restaurada é corpo de texto: "paragrafo". titulo_4 é só o título do texto de terceiro.
const RESTORED_QUOTE_TIPO = "paragrafo";

function insertIndex(
  conteudo: unknown[],
  region: string,
  pdfText: string,
): number {
  const pdfFlat = collapseQuotes(pdfText);
  const needle = collapseQuotes(region).slice(0, 48);
  const pos = needle ? pdfFlat.indexOf(needle) : -1;
  if (pos < 0) return conteudo.length;
  const prefix = pdfFlat.slice(0, pos);
  let last = 0;
  for (let i = 0; i < conteudo.length; i++) {
    const block = conteudo[i];
    const snippet = collapseQuotes(
      block && typeof block === "object"
        ? editorialPlainText(block)
        : String(block || ""),
    );
    if (snippet && prefix.includes(snippet.slice(0, 36))) last = i + 1;
  }
  return last;
}

export function restoreMissingQuoteRegions(
  pageStructure: Record<string, unknown> | null | undefined,
  regions: string[],
  options: { pdfText?: string; literary?: boolean } = {},
): Record<string, unknown> | null | undefined {
  if (!pageStructure || typeof pageStructure !== "object") return pageStructure;
  if (!regions.length) return pageStructure;
  const conteudo = pageStructure.conteudo;
  if (!Array.isArray(conteudo)) return pageStructure;

  let editorial = editorialPlainText(pageStructure);
  const missing = regions.filter((region) => !quoteRegionPresent(region, editorial));
  if (!missing.length) return pageStructure;

  const tipo = RESTORED_QUOTE_TIPO;
  const out = [...conteudo];
  const pdf = options.pdfText || "";
  for (const region of missing) {
    if (quoteRegionPresent(region, editorial)) continue;
    const idx = insertIndex(out, region, pdf);
    out.splice(idx, 0, { tipo, texto: region });
    editorial = `${editorial} ${region}`;
  }
  return { ...pageStructure, conteudo: out };
}

export function restoreQuotesFromPageStyles(
  pageStructure: Record<string, unknown> | null | undefined,
  pageStyles: PageTextStyles | null | undefined,
  options: { pdfText?: string; literary?: boolean } = {},
): Record<string, unknown> | null | undefined {
  let regions: string[] = [];
  if (pageStyles?.runs?.length) {
    regions = extractQuoteRegionsFromRuns(pageStyles.runs);
  }
  const pdf = options.pdfText || "";
  if (pdf) {
    const extra = extractQuoteRegions(pdf);
    const seen = new Set(regions.map((r) => collapseQuotes(r)));
    for (const region of extra) {
      const key = collapseQuotes(region);
      if (!seen.has(key)) {
        regions.push(region);
        seen.add(key);
      }
    }
  }
  return restoreMissingQuoteRegions(pageStructure, regions, {
    pdfText: pdf || (pageStyles ? pageStyles.runs.map((r) => r.text).join("") : ""),
    literary: options.literary,
  });
}
