/** Créditos de imagem não entram no JSON. Espelha src/pipeline/steps/image_credits.py */

const AGENCY_RE =
  /\b(?:shutterstock|getty(?:\s+images)?|alamy|istock(?:photo)?|adobe\s+stock|dreamstime|123rf|acervo\s+da\s+editora|acervo\s+pessoal|arquivo\s+da\s+editora)\b/i;
const LABEL_RE = /(?:foto|fotografia|cr[eé]ditos?)\s*:\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ][^.\n]{1,70}/gi;
const YEAR_RE = /\b(?:19|20)\d{2}\b/;

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
  "legenda",
  "fonte",
  "contexto_pedagogico",
]);

function letters(text: string): string {
  return text.replace(/[^\p{L}]/gu, "");
}

function isSlashCredit(fragment: string): boolean {
  const raw = fragment.trim().replace(/^[ \t.;,\-]+|[ \t.;,\-]+$/g, "");
  if (!raw || raw.length > 90 || raw.split("/").length !== 2 || raw.includes(",")) return false;
  if (YEAR_RE.test(raw)) return false;
  const [left, right] = raw.split("/").map((part) => part.trim());
  if (letters(left).length < 2 || letters(right).length < 2) return false;
  if (AGENCY_RE.test(raw)) return true;
  const chars = letters(raw);
  if (chars.length < 6) return false;
  const upper = [...chars].filter((ch) => ch === ch.toUpperCase() && ch !== ch.toLowerCase()).length;
  return upper / chars.length >= 0.7;
}

export function isImageCredit(text: string): boolean {
  const raw = (text || "").replace(/\s+/g, " ").trim().replace(/^[ \t.;,\-]+|[ \t.;,\-]+$/g, "");
  if (!raw || raw.length > 120) return false;
  if (YEAR_RE.test(raw) && !AGENCY_RE.test(raw)) return false;
  if (AGENCY_RE.test(raw) && raw.length <= 80 && raw.split(".").length <= 2) return true;
  if (isSlashCredit(raw) && raw.length <= 80) return true;
  return /^(?:foto|fotografia|cr[eé]ditos?)\s*:\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ]/i.test(raw) && raw.split(/\s+/).length <= 8;
}

function wordsBefore(text: string, end: number, limit: number): { start: number; count: number } | null {
  const spans: Array<{ start: number; end: number }> = [];
  let cursor = end;
  while (spans.length < limit) {
    let at = cursor;
    while (at > 0 && (text[at - 1] === " " || text[at - 1] === "\t")) at -= 1;
    let start = at;
    while (start > 0 && /[\p{L}\p{N}'’.\-]/u.test(text[start - 1])) start -= 1;
    const word = text.slice(start, at);
    if (!word || !/^[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w'’.\-]*$/.test(word)) break;
    spans.push({ start, end: at });
    cursor = start;
  }
  if (!spans.length) return null;
  return { start: spans[spans.length - 1].start, count: spans.length };
}

function wordsAfter(text: string, start: number, limit: number): number | null {
  let i = start;
  while (i < text.length && (text[i] === " " || text[i] === "\t")) i += 1;
  let count = 0;
  let end = i;
  while (count < limit && i < text.length) {
    const match = /^[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w'’.\-]*/.exec(text.slice(i));
    if (!match) break;
    end = i + match[0].length;
    count += 1;
    i = end;
    if (count >= limit) break;
    if (i < text.length && (text[i] === " " || text[i] === "\t")) {
      while (i < text.length && (text[i] === " " || text[i] === "\t")) i += 1;
      continue;
    }
    break;
  }
  return count ? end : null;
}

function stripSlashCredits(text: string): string {
  const cuts: Array<[number, number]> = [];
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] !== "/") continue;
    const left = wordsBefore(text, i, 4);
    if (!left) continue;
    const rightEnd = wordsAfter(text, i + 1, Math.max(left.count, 2));
    if (rightEnd == null) continue;
    const fragment = text.slice(left.start, rightEnd);
    if (isSlashCredit(fragment)) cuts.push([left.start, rightEnd]);
  }
  let out = text;
  for (const [start, end] of cuts.reverse()) out = `${out.slice(0, start)} ${out.slice(end)}`;
  return out;
}

export function stripImageCredits(text: string): string {
  if (!text) return text;
  return stripSlashCredits(text)
    .replace(AGENCY_RE, " ")
    .replace(LABEL_RE, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function blockText(node: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const key of ["texto", "trecho", "legenda", "fonte"]) {
    const value = node[key];
    if (typeof value === "string" && value.trim()) parts.push(value.trim());
  }
  return parts.join(" ").trim();
}

export function omitImageCredits(node: unknown): unknown {
  if (Array.isArray(node)) {
    const kept: unknown[] = [];
    for (const item of node) {
      const cleaned = omitImageCredits(item);
      if (cleaned && typeof cleaned === "object" && !Array.isArray(cleaned)) {
        const block = cleaned as Record<string, unknown>;
        if (block.tipo === "fonte") {
          const text = blockText(block);
          if (!text || isImageCredit(text)) continue;
        }
        if ("trecho" in block && !String(block.trecho || "").trim()) continue;
      }
      kept.push(cleaned);
    }
    return kept;
  }
  if (!node || typeof node !== "object") return node;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    if (TEXT_KEYS.has(key) && typeof value === "string") {
      if (isImageCredit(value) || (key === "fonte" && !stripImageCredits(value))) {
        out[key] = key === "fonte" ? null : "";
      } else {
        const cleaned = stripImageCredits(value);
        out[key] = key === "fonte" && isImageCredit(cleaned) ? null : cleaned;
      }
    } else {
      out[key] = omitImageCredits(value);
    }
  }
  return out;
}
