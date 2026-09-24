/**
 * Merge de estilos tipográficos (negrito/itálico) no JSON editorial.
 * Espelha src/pipeline/steps/style_merge.py — regras alinhadas ao worker Python.
 */

export type TextRun = { text: string; estilo: string };

export type PageTextStyles = {
  page_number: number;
  runs: TextRun[];
  char_count: number;
};

export type TextSpansPayload = {
  pages: PageTextStyles[];
  total_pages: number;
  total_chars: number;
};

const STYLE_KEYS = new Set([
  "texto",
  "trecho",
  "instrucao",
  "titulo_quadro",
  "titulo_boxe",
  "titulo_tabela",
  "cabecalho",
]);

const FONT_STYLES = new Set(["normal", "negrito", "italico", "negrito_italico"]);
const VISUAL_STYLES = new Set(["circulado", "sublinhado", "tachado"]);
const QUOTE_CHARS = new Set([
  '"',
  "'",
  "\u201c",
  "\u201d",
  "\u201e",
  "\u201f",
  "\u00ab",
  "\u00bb",
  "\u2039",
  "\u203a",
  "\u201a",
  "\u2018",
  "\u2019",
  "\u201b",
]);
const QUOTE_SENTINEL = "\u0001";
const MIN_FUZZY_RATIO = 0.9;
const MIN_FUZZY_RATIO_SHORT = 0.95;
const MIN_FUZZY_NEEDLE = 4;
const MIN_SCANNED_CHARS = 20;

const BOLD_NAME_RE = /(bold|black|heavy|semibold|demi)/i;
const ITALIC_NAME_RE = /(italic|oblique)/i;

export function classifyFontStyleFromName(fontName: string): string {
  const bold = BOLD_NAME_RE.test(fontName || "");
  const italic = ITALIC_NAME_RE.test(fontName || "");
  if (bold && italic) return "negrito_italico";
  if (bold) return "negrito";
  if (italic) return "italico";
  return "normal";
}

function normalizeForAlign(text: string): string {
  if (!text) return "";
  let s = text.normalize("NFKC").replace(/\u00ad/g, "");
  let out = "";
  for (const ch of s) {
    out += QUOTE_CHARS.has(ch) ? QUOTE_SENTINEL : ch;
  }
  s = out.replace(/[\u2010-\u2015\u2212\-]+/g, "-").replace(/\s+/g, " ");
  return s.toLocaleLowerCase().trim();
}

function buildNormIndex(original: string): { norm: string; normToOrig: number[] } {
  if (!original) return { norm: "", normToOrig: [] };
  const expanded: Array<{ ch: string; orig: number }> = [];
  for (let idx = 0; idx < original.length; idx++) {
    const ch = original[idx];
    if (ch === "\u00ad") continue;
    const piece = ch.normalize("NFKC");
    for (const p of piece) {
      if (QUOTE_CHARS.has(p)) expanded.push({ ch: QUOTE_SENTINEL, orig: idx });
      else if (/[\u2010-\u2015\u2212\-]/.test(p)) expanded.push({ ch: "-", orig: idx });
      else expanded.push({ ch: p, orig: idx });
    }
  }
  const normChars: string[] = [];
  const normToOrig: number[] = [];
  let prevSpace = false;
  for (const { ch, orig } of expanded) {
    if (/\s/.test(ch)) {
      if (prevSpace || normChars.length === 0) continue;
      normChars.push(" ");
      normToOrig.push(orig);
      prevSpace = true;
      continue;
    }
    prevSpace = false;
    normChars.push(ch.toLocaleLowerCase());
    normToOrig.push(orig);
  }
  while (normChars.length && normChars[normChars.length - 1] === " ") {
    normChars.pop();
    normToOrig.pop();
  }
  return { norm: normChars.join(""), normToOrig };
}

function ratio(a: string, b: string): number {
  if (!a && !b) return 1;
  if (!a || !b) return 0;
  const m = a.length;
  const n = b.length;
  const dp: number[] = new Array(n + 1);
  for (let j = 0; j <= n; j++) dp[j] = j;
  for (let i = 1; i <= m; i++) {
    let prev = dp[0];
    dp[0] = i;
    for (let j = 1; j <= n; j++) {
      const tmp = dp[j];
      if (a[i - 1] === b[j - 1]) dp[j] = prev;
      else dp[j] = 1 + Math.min(prev, dp[j], dp[j - 1]);
      prev = tmp;
    }
  }
  const dist = dp[n];
  return 1 - dist / Math.max(m, n);
}

function findFuzzy(
  haystack: string,
  needle: string,
  start: number,
): { start: number; end: number } | null {
  if (!needle || start >= haystack.length) return null;
  const nlen = needle.length;
  if (nlen < MIN_FUZZY_NEEDLE) return null;
  const window = haystack.slice(start);
  if (!window) return null;
  const threshold = nlen < 20 ? MIN_FUZZY_RATIO_SHORT : MIN_FUZZY_RATIO;
  const minW = Math.max(nlen - 2, Math.floor(nlen * 0.9), 1);
  const maxW = Math.min(window.length, Math.floor(nlen * 1.15) + 4);
  let best: { score: number; start: number; end: number } | null = null;
  const anchor = needle.slice(0, Math.min(8, nlen));
  const candidates: number[] = [];
  if (anchor.length >= 3) {
    let pos = 0;
    while (candidates.length < 40) {
      const found = window.indexOf(anchor, pos);
      if (found < 0) break;
      candidates.push(found);
      pos = found + 1;
    }
  }
  if (!candidates.length) {
    const step = Math.max(1, Math.floor(window.length / 80));
    for (let i = 0; i < Math.min(window.length, nlen * 3 + 50); i += step) {
      candidates.push(i);
    }
  }
  for (const c of candidates) {
    for (let w = minW; w <= maxW; w++) {
      const end = c + w;
      if (end > window.length) break;
      const score = ratio(needle, window.slice(c, end));
      if (!best || score > best.score) {
        best = { score, start: start + c, end: start + end };
      }
    }
  }
  if (!best || best.score < threshold) return null;
  if (best.end - best.start < Math.floor(nlen * 0.85)) return null;
  return { start: best.start, end: best.end };
}

function isWordChar(ch: string): boolean {
  return /[0-9A-Za-zÀ-ÿ_]/.test(ch) || ch === "\u00ad";
}

function coalesceMidwordStyleBreaks(text: string, styles: string[]): string[] {
  if (!text || styles.length !== text.length) return styles;
  const out = [...styles];
  let i = 0;
  while (i < text.length) {
    if (!isWordChar(text[i])) {
      i += 1;
      continue;
    }
    let j = i;
    while (j < text.length && isWordChar(text[j])) j += 1;
    const wordStyles = out.slice(i, j);
    const unique = new Set(wordStyles);
    if (unique.size > 1) {
      const counts = new Map<string, number>();
      for (const s of wordStyles) counts.set(s, (counts.get(s) || 0) + 1);
      let best = "normal";
      let bestScore = -1;
      for (const [s, c] of counts) {
        const score = c * 10 + (s === "normal" ? 0 : 1);
        if (score > bestScore) {
          bestScore = score;
          best = s;
        }
      }
      for (let k = i; k < j; k++) out[k] = best;
    }
    i = j;
  }
  return out;
}

function flattenFieldText(value: unknown): { text: string; visual: Array<string | null> } {
  if (typeof value === "string") {
    return { text: value, visual: Array(value.length).fill(null) };
  }
  if (Array.isArray(value)) {
    let text = "";
    const visual: Array<string | null> = [];
    for (const item of value) {
      if (item && typeof item === "object" && !Array.isArray(item)) {
        const trecho = String((item as Record<string, unknown>).trecho ?? "");
        const estilo = String((item as Record<string, unknown>).estilo ?? "normal");
        const v = VISUAL_STYLES.has(estilo) ? estilo : null;
        text += trecho;
        for (let i = 0; i < trecho.length; i++) visual.push(v);
      } else if (typeof item === "string") {
        text += item;
        for (let i = 0; i < item.length; i++) visual.push(null);
      }
    }
    return { text, visual };
  }
  return { text: "", visual: [] };
}

function segmentsFromStyles(
  text: string,
  fontStyles: string[],
  visualStyles: Array<string | null>,
): string | Array<{ trecho: string; estilo: string }> {
  if (!text) return text;
  const n = text.length;
  const effective: string[] = [];
  for (let i = 0; i < n; i++) {
    if (visualStyles[i]) effective.push(visualStyles[i]!);
    else {
      const e = fontStyles[i] || "normal";
      effective.push(FONT_STYLES.has(e) ? e : "normal");
    }
  }
  if (effective.every((s) => s === "normal")) return text;
  const segments: Array<{ trecho: string; estilo: string }> = [];
  let start = 0;
  let cur = effective[0];
  for (let i = 1; i < n; i++) {
    if (effective[i] !== cur) {
      segments.push({ trecho: text.slice(start, i), estilo: cur });
      start = i;
      cur = effective[i];
    }
  }
  segments.push({ trecho: text.slice(start), estilo: cur });
  return segments;
}

function leadingTrailingQuotes(pdfSlice: string): { leading: string; trailing: string } {
  let leading = "";
  let trailing = "";
  let i = 0;
  while (i < pdfSlice.length && QUOTE_CHARS.has(pdfSlice[i])) {
    leading += pdfSlice[i];
    i++;
  }
  let j = pdfSlice.length - 1;
  while (j >= i && QUOTE_CHARS.has(pdfSlice[j])) {
    trailing = pdfSlice[j] + trailing;
    j--;
  }
  return { leading, trailing };
}

function alignField(
  jsonText: string,
  visual: Array<string | null>,
  pdfText: string,
  pdfStyles: string[],
  pdfNorm: string,
  pdfNormToOrig: number[],
  cursor: number,
): { value: string | Array<{ trecho: string; estilo: string }>; cursor: number; aligned: number } {
  const unchanged = () => {
    if (visual.every((v) => v == null)) return { value: jsonText, cursor, aligned: 0 };
    return {
      value: segmentsFromStyles(jsonText, Array(jsonText.length).fill("normal"), visual),
      cursor,
      aligned: 0,
    };
  };

  if (!jsonText.trim()) return unchanged();
  const { norm: jsonNorm, normToOrig: jsonNormToOrig } = buildNormIndex(jsonText);
  if (!jsonNorm || !pdfNorm) return unchanged();

  let startNorm = 0;
  if (cursor > 0 && cursor < pdfText.length) {
    let found = false;
    for (let ni = 0; ni < pdfNormToOrig.length; ni++) {
      if (pdfNormToOrig[ni] >= cursor) {
        startNorm = ni;
        found = true;
        break;
      }
    }
    if (!found) startNorm = pdfNorm.length;
  }

  let matchStart = pdfNorm.indexOf(jsonNorm, startNorm);
  let matchEnd = matchStart >= 0 ? matchStart + jsonNorm.length : -1;
  if (matchStart < 0) {
    let fuzzy = findFuzzy(pdfNorm, jsonNorm, startNorm);
    if (!fuzzy && startNorm > 0) fuzzy = findFuzzy(pdfNorm, jsonNorm, 0);
    if (!fuzzy) return unchanged();
    matchStart = fuzzy.start;
    matchEnd = fuzzy.end;
  }

  const origIndices = pdfNormToOrig.slice(matchStart, matchEnd);
  if (!origIndices.length) return unchanged();
  let pdfOrigStart = origIndices[0];
  let pdfOrigEnd = origIndices[origIndices.length - 1] + 1;
  while (pdfOrigStart > 0 && QUOTE_CHARS.has(pdfText[pdfOrigStart - 1])) pdfOrigStart--;
  while (pdfOrigEnd < pdfText.length && QUOTE_CHARS.has(pdfText[pdfOrigEnd])) pdfOrigEnd++;
  const pdfSlice = pdfText.slice(pdfOrigStart, pdfOrigEnd);

  const fontByOrig = Array(jsonText.length).fill("normal");
  const jsonSpan = matchEnd - matchStart;
  for (let ji = 0; ji < jsonNormToOrig.length; ji++) {
    if (jsonSpan <= 0) break;
    const rel = ji / Math.max(jsonNormToOrig.length, 1);
    const pdfRel = jsonSpan > 1 ? Math.floor(rel * (jsonSpan - 1)) : 0;
    const pdfNi = matchStart + Math.min(pdfRel, jsonSpan - 1);
    if (pdfNi >= 0 && pdfNi < pdfNormToOrig.length) {
      const pdfOi = pdfNormToOrig[pdfNi];
      if (pdfOi >= 0 && pdfOi < pdfStyles.length) fontByOrig[jsonNormToOrig[ji]] = pdfStyles[pdfOi];
    }
  }
  const mapped = Array(jsonText.length).fill(false);
  for (const jOrig of jsonNormToOrig) {
    if (jOrig >= 0 && jOrig < mapped.length) mapped[jOrig] = true;
  }
  let last = "normal";
  for (let i = 0; i < fontByOrig.length; i++) {
    if (mapped[i]) last = fontByOrig[i];
    else fontByOrig[i] = last;
  }
  let coalesced = coalesceMidwordStyleBreaks(jsonText, fontByOrig);

  const { leading, trailing } = leadingTrailingQuotes(pdfSlice);
  let outText = jsonText;
  let outVisual = visual;
  let outFont = coalesced;
  const prefix =
    leading && (!jsonText || !QUOTE_CHARS.has(jsonText[0])) ? leading : "";
  const suffix =
    trailing && (!jsonText || !QUOTE_CHARS.has(jsonText[jsonText.length - 1]))
      ? trailing
      : "";
  if (prefix || suffix) {
    outText = prefix + jsonText + suffix;
    const inheritStart = coalesced[0] || "normal";
    const inheritEnd = coalesced[coalesced.length - 1] || "normal";
    outFont = [
      ...Array(prefix.length).fill(inheritStart),
      ...coalesced,
      ...Array(suffix.length).fill(inheritEnd),
    ];
    outVisual = [
      ...Array(prefix.length).fill(null),
      ...visual,
      ...Array(suffix.length).fill(null),
    ];
    outFont = coalesceMidwordStyleBreaks(outText, outFont);
  }

  return {
    value: segmentsFromStyles(outText, outFont, outVisual),
    cursor: pdfOrigEnd,
    aligned: jsonText.length,
  };
}

function flattenRuns(runs: TextRun[]): { text: string; styles: string[] } {
  let text = "";
  const styles: string[] = [];
  for (const run of runs) {
    for (const ch of run.text) {
      text += ch;
      styles.push(FONT_STYLES.has(run.estilo) ? run.estilo : "normal");
    }
  }
  return { text, styles };
}

function walkAndMerge(
  node: unknown,
  pdfText: string,
  pdfStyles: string[],
  pdfNorm: string,
  pdfNormToOrig: number[],
  cursor: { value: number },
): unknown {
  if (node && typeof node === "object" && !Array.isArray(node)) {
    const obj = node as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj)) {
      if (key === "descricao") {
        out[key] = value;
        continue;
      }
      if (STYLE_KEYS.has(key)) {
        const { text, visual } = flattenFieldText(value);
        const result = alignField(
          text,
          visual,
          pdfText,
          pdfStyles,
          pdfNorm,
          pdfNormToOrig,
          cursor.value,
        );
        if (result.aligned > 0) cursor.value = result.cursor;
        out[key] = result.value;
      } else {
        out[key] = walkAndMerge(value, pdfText, pdfStyles, pdfNorm, pdfNormToOrig, cursor);
      }
    }
    return out;
  }
  if (Array.isArray(node)) {
    return node.map((item) =>
      walkAndMerge(item, pdfText, pdfStyles, pdfNorm, pdfNormToOrig, cursor),
    );
  }
  return node;
}

export function mergeStylesIntoPage(
  pageStructure: Record<string, unknown>,
  pageStyles: PageTextStyles | null | undefined,
): Record<string, unknown> {
  if (!pageStructure || typeof pageStructure !== "object") return pageStructure;
  if (
    !pageStyles ||
    pageStyles.char_count < MIN_SCANNED_CHARS ||
    !pageStyles.runs?.length
  ) {
    return pageStructure;
  }
  const { text: pdfText, styles: pdfStyles } = flattenRuns(pageStyles.runs);
  const { norm: pdfNorm, normToOrig: pdfNormToOrig } = buildNormIndex(pdfText);
  if (!pdfNorm) return pageStructure;
  const cursor = { value: 0 };
  const merged = walkAndMerge(
    pageStructure,
    pdfText,
    pdfStyles,
    pdfNorm,
    pdfNormToOrig,
    cursor,
  );
  return merged && typeof merged === "object" && !Array.isArray(merged)
    ? (merged as Record<string, unknown>)
    : pageStructure;
}

export function pagesFromPayload(payload: unknown): Map<number, PageTextStyles> {
  const out = new Map<number, PageTextStyles>();
  if (!payload || typeof payload !== "object") return out;
  const pages = (payload as TextSpansPayload).pages;
  if (!Array.isArray(pages)) return out;
  for (const item of pages) {
    if (!item || typeof item !== "object") continue;
    const pageNumber = Number(item.page_number) || 0;
    if (pageNumber <= 0) continue;
    const runs: TextRun[] = [];
    if (Array.isArray(item.runs)) {
      for (const run of item.runs) {
        if (!run || typeof run !== "object") continue;
        const text = String(run.text || "");
        let estilo = String(run.estilo || "normal");
        if (!FONT_STYLES.has(estilo)) estilo = "normal";
        if (text) runs.push({ text, estilo });
      }
    }
    const charCount =
      Number(item.char_count) || runs.reduce((acc, r) => acc + r.text.length, 0);
    out.set(pageNumber, { page_number: pageNumber, runs, char_count: charCount });
  }
  return out;
}

/** Exportado para testes leves / debug. */
export { normalizeForAlign };
