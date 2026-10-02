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
  "titulo",
  "titulo_1",
  "titulo_2",
  "titulo_3",
  "titulo_4",
  "titulo_5",
  "enunciado",
  "termo",
  "valor",
  "legenda",
  "fonte",
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
const ITALIC_NAME_RE = /(italic|oblique|kursiv|cursive|(?<![a-z])ital(?![a-z]))/i;
const ITALIC_SUFFIX_RE = /[,+\-_](it|i)(?:mt|std)?$/i;
const ITALIC_SHORT = new Set(["heit", "hebi", "tito", "tibo", "coui", "cobo"]);
const BOLD_SHORT = new Set(["hebo", "hebi", "tibo", "cobo"]);

function fontBasename(name: string): string {
  const raw = (name || "").trim();
  const plus = raw.lastIndexOf("+");
  return plus >= 0 ? raw.slice(plus + 1) : raw;
}

export function classifyFontStyleFromName(fontName: string): string {
  const base = fontBasename(fontName);
  const bold = BOLD_SHORT.has(base.toLowerCase()) || BOLD_NAME_RE.test(base);
  const italic =
    ITALIC_SHORT.has(base.toLowerCase()) ||
    ITALIC_NAME_RE.test(base) ||
    ITALIC_SUFFIX_RE.test(base);
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

type Opcode = {
  tag: "equal" | "replace" | "insert" | "delete";
  i1: number;
  i2: number;
  j1: number;
  j2: number;
};

function longestMatch(
  a: string,
  b: string,
  alo: number,
  ahi: number,
  blo: number,
  bhi: number,
): { i: number; j: number; size: number } {
  let bestI = alo;
  let bestJ = blo;
  let bestSize = 0;
  const jFor: Record<string, number[]> = {};
  for (let j = blo; j < bhi; j++) {
    const ch = b[j];
    (jFor[ch] ||= []).push(j);
  }
  let j2len: Record<number, number> = {};
  for (let i = alo; i < ahi; i++) {
    const newj2len: Record<number, number> = {};
    for (const j of jFor[a[i]] || []) {
      if (j < blo) continue;
      if (j >= bhi) break;
      const k = (j2len[j - 1] || 0) + 1;
      newj2len[j] = k;
      if (k > bestSize) {
        bestI = i - k + 1;
        bestJ = j - k + 1;
        bestSize = k;
      }
    }
    j2len = newj2len;
  }
  return { i: bestI, j: bestJ, size: bestSize };
}

function matchingBlocks(a: string, b: string): Array<{ i: number; j: number; size: number }> {
  const queue: Array<[number, number, number, number]> = [[0, a.length, 0, b.length]];
  const matches: Array<{ i: number; j: number; size: number }> = [];
  while (queue.length) {
    const [alo, ahi, blo, bhi] = queue.pop()!;
    const { i, j, size } = longestMatch(a, b, alo, ahi, blo, bhi);
    if (size <= 0) continue;
    matches.push({ i, j, size });
    if (alo < i && blo < j) queue.push([alo, i, blo, j]);
    if (i + size < ahi && j + size < bhi) queue.push([i + size, ahi, j + size, bhi]);
  }
  matches.sort((x, y) => x.i - y.i || x.j - y.j);
  const collapsed: Array<{ i: number; j: number; size: number }> = [];
  for (const m of matches) {
    const last = collapsed[collapsed.length - 1];
    if (last && last.i + last.size === m.i && last.j + last.size === m.j) {
      last.size += m.size;
    } else {
      collapsed.push({ ...m });
    }
  }
  collapsed.push({ i: a.length, j: b.length, size: 0 });
  return collapsed;
}

function getOpcodes(a: string, b: string): Opcode[] {
  const blocks = matchingBlocks(a, b);
  const ops: Opcode[] = [];
  let i = 0;
  let j = 0;
  for (const m of blocks) {
    if (i < m.i || j < m.j) {
      let tag: Opcode["tag"] = "replace";
      if (i === m.i) tag = "insert";
      else if (j === m.j) tag = "delete";
      ops.push({ tag, i1: i, i2: m.i, j1: j, j2: m.j });
    }
    if (m.size) {
      ops.push({ tag: "equal", i1: m.i, i2: m.i + m.size, j1: m.j, j2: m.j + m.size });
    }
    i = m.i + m.size;
    j = m.j + m.size;
  }
  return ops;
}

function projectStylesByOpcodes(
  jsonText: string,
  jsonNorm: string,
  jsonNormToOrig: number[],
  pdfNormSlice: string,
  pdfStyles: string[],
  pdfNormToOrig: number[],
  matchStart: number,
): string[] {
  const fontByOrig = Array(jsonText.length).fill("normal");
  for (const op of getOpcodes(jsonNorm, pdfNormSlice)) {
    if (op.tag === "equal") {
      for (let k = 0; k < op.i2 - op.i1; k++) {
        const ji = op.i1 + k;
        const pj = matchStart + op.j1 + k;
        if (ji < jsonNormToOrig.length && pj < pdfNormToOrig.length) {
          const jOrig = jsonNormToOrig[ji];
          const pdfOi = pdfNormToOrig[pj];
          if (jOrig >= 0 && jOrig < fontByOrig.length && pdfOi >= 0 && pdfOi < pdfStyles.length) {
            fontByOrig[jOrig] = pdfStyles[pdfOi];
          }
        }
      }
    } else if (op.tag === "replace" && op.i2 > op.i1 && op.j2 > op.j1) {
      for (let k = 0; k < op.i2 - op.i1; k++) {
        const ji = op.i1 + k;
        const rel = k / Math.max(op.i2 - op.i1, 1);
        const pj =
          matchStart + op.j1 + Math.min(Math.floor(rel * (op.j2 - op.j1)), op.j2 - op.j1 - 1);
        if (ji < jsonNormToOrig.length && pj >= 0 && pj < pdfNormToOrig.length) {
          const jOrig = jsonNormToOrig[ji];
          const pdfOi = pdfNormToOrig[pj];
          if (jOrig >= 0 && jOrig < fontByOrig.length && pdfOi >= 0 && pdfOi < pdfStyles.length) {
            fontByOrig[jOrig] = pdfStyles[pdfOi];
          }
        }
      }
    }
  }
  return fontByOrig;
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
  const pdfNormSlice = pdfNorm.slice(matchStart, matchEnd);

  const fontByOrig = projectStylesByOpcodes(
    jsonText,
    jsonNorm,
    jsonNormToOrig,
    pdfNormSlice,
    pdfStyles,
    pdfNormToOrig,
    matchStart,
  );
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

function phraseOk(phrase: string): boolean {
  const stripped = (phrase || "").trim();
  if (stripped.length < 4) return false;
  let letters = 0;
  for (const ch of stripped) {
    if (/\p{L}/u.test(ch)) letters += 1;
  }
  return letters >= 3;
}

function emphasisPhrases(runs: TextRun[]): Array<{ phrase: string; estilo: string }> {
  const { text, styles } = flattenRuns(runs);
  const coalesced = coalesceMidwordStyleBreaks(text, styles);
  const phrases: Array<{ phrase: string; estilo: string }> = [];
  let i = 0;
  while (i < text.length) {
    const estilo = coalesced[i];
    if (estilo !== "italico" && estilo !== "negrito_italico") {
      i += 1;
      continue;
    }
    let j = i + 1;
    while (j < text.length && coalesced[j] === estilo) j += 1;
    const phrase = text.slice(i, j);
    if (phraseOk(phrase)) phrases.push({ phrase, estilo });
    i = j;
  }
  return phrases;
}

function fontFromField(value: unknown, n: number): string[] {
  if (typeof value === "string") return Array(n).fill("normal");
  const fonts: string[] = [];
  if (Array.isArray(value)) {
    for (const item of value) {
      if (item && typeof item === "object" && !Array.isArray(item)) {
        const trecho = String((item as Record<string, unknown>).trecho ?? "");
        const estilo = String((item as Record<string, unknown>).estilo ?? "normal");
        const font = FONT_STYLES.has(estilo) ? estilo : "normal";
        for (let i = 0; i < trecho.length; i++) fonts.push(font);
      } else if (typeof item === "string") {
        for (let i = 0; i < item.length; i++) fonts.push("normal");
      }
    }
  }
  while (fonts.length < n) fonts.push("normal");
  return fonts.slice(0, n);
}

function paintPhrase(
  text: string,
  font: string[],
  visual: Array<string | null>,
  phrase: string,
  estilo: string,
): boolean {
  const needle = phrase.trim();
  if (!needle || needle.length > text.length) return false;
  const hay = text.toLocaleLowerCase();
  const needleCf = needle.toLocaleLowerCase();
  let start = 0;
  let changed = false;
  while (start <= hay.length - needleCf.length) {
    const idx = hay.indexOf(needleCf, start);
    if (idx < 0) break;
    for (let k = 0; k < needle.length; k++) {
      const pos = idx + k;
      if (pos >= font.length) break;
      if (visual[pos]) continue;
      if (font[pos] === "normal") {
        font[pos] = estilo;
        changed = true;
      }
    }
    start = idx + Math.max(needle.length, 1);
  }
  return changed;
}

function applyOrphanEmphasis(
  node: Record<string, unknown>,
  runs: TextRun[],
): Record<string, unknown> {
  const phrases = emphasisPhrases(runs);
  if (!phrases.length) return node;

  const walk = (n: unknown): unknown => {
    if (n && typeof n === "object" && !Array.isArray(n)) {
      const obj = n as Record<string, unknown>;
      const out: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(obj)) {
        if (key === "descricao") {
          out[key] = value;
          continue;
        }
        if (STYLE_KEYS.has(key)) {
          const { text, visual } = flattenFieldText(value);
          if (!text) {
            out[key] = value;
            continue;
          }
          const font = fontFromField(value, text.length);
          let changed = false;
          for (const { phrase, estilo } of phrases) {
            if (paintPhrase(text, font, visual, phrase, estilo)) changed = true;
          }
          out[key] = changed
            ? segmentsFromStyles(text, coalesceMidwordStyleBreaks(text, font), visual)
            : value;
        } else {
          out[key] = walk(value);
        }
      }
      return out;
    }
    if (Array.isArray(n)) return n.map((item) => walk(item));
    return n;
  };

  const walked = walk(node);
  return walked && typeof walked === "object" && !Array.isArray(walked)
    ? (walked as Record<string, unknown>)
    : node;
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
  const withOrphans =
    merged && typeof merged === "object" && !Array.isArray(merged)
      ? applyOrphanEmphasis(merged as Record<string, unknown>, pageStyles.runs)
      : merged;
  return withOrphans && typeof withOrphans === "object" && !Array.isArray(withOrphans)
    ? (withOrphans as Record<string, unknown>)
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
