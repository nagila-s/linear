/**
 * Classificação de negrito/itálico a partir do nome da fonte e do transform do PDF.js.
 * Espelha src/pipeline/steps/pdf_text_styles.py.
 */

const BOLD_NAME_RE = /(bold|black|heavy|semibold|demi)/i;
const ITALIC_NAME_RE = /(italic|oblique|kursiv|cursive|(?<![a-z])ital(?![a-z]))/i;
const ITALIC_SUFFIX_RE = /[,+\-_](it|i)(?:mt|std)?$/i;
const ITALIC_SHORT_NAMES = new Set(["heit", "hebi", "tito", "tibo", "coui", "cobo"]);
const BOLD_SHORT_NAMES = new Set(["hebo", "hebi", "tibo", "cobo"]);
const ITALIC_SHEAR_RATIO = 0.15;

function fontBasename(name: string): string {
  const raw = (name || "").trim();
  const plus = raw.lastIndexOf("+");
  return plus >= 0 ? raw.slice(plus + 1) : raw;
}

function nameLooksBold(name: string): boolean {
  const base = fontBasename(name);
  if (!base) return false;
  if (BOLD_SHORT_NAMES.has(base.toLowerCase())) return true;
  return BOLD_NAME_RE.test(base);
}

function nameLooksItalic(name: string): boolean {
  const base = fontBasename(name);
  if (!base) return false;
  if (ITALIC_SHORT_NAMES.has(base.toLowerCase())) return true;
  if (ITALIC_NAME_RE.test(base)) return true;
  return ITALIC_SUFFIX_RE.test(base);
}

/** Cisalhamento de itálico falso, sem tratar texto rotacionado como ênfase. */
export function transformLooksItalic(transform: number[] | undefined): boolean {
  if (!Array.isArray(transform) || transform.length < 4) return false;
  const a = transform[0];
  const b = transform[1] || 0;
  const c = transform[2] || 0;
  const d = transform[3];
  const scaleX = Math.hypot(a, b) || 1;
  const shear = Math.abs(c) / (Math.abs(a) > 1e-6 ? Math.abs(a) : scaleX);
  const rotLike = Math.abs(b) / scaleX;
  if (rotLike > 0.25) return false;
  return shear >= ITALIC_SHEAR_RATIO;
}

export function classifyFontStyleFromName(
  fontName: string,
  transform?: number[],
): string {
  const bold = nameLooksBold(fontName);
  let italic = nameLooksItalic(fontName);
  if (!italic && transformLooksItalic(transform)) italic = true;
  if (bold && italic) return "negrito_italico";
  if (bold) return "negrito";
  if (italic) return "italico";
  return "normal";
}
