/** Roteamento de prompts para a área de testes (sem fallback para disco do worker). */

export const PAGE_TYPES = [
  "capa",
  "autores",
  "ficha",
  "apresentacao",
  "conheca",
  "sumario",
  "hino",
  "referencias",
  "contracapa",
  "conteudo",
] as const;

export type PageType = (typeof PAGE_TYPES)[number];

export const CONTENT_PAGE_TYPE: PageType = "conteudo";

export const PROMPT_FILES: Record<PageType, string> = {
  capa: "capa.txt",
  autores: "autores.txt",
  ficha: "ficha.txt",
  apresentacao: "apresentacao.txt",
  conheca: "conheca.txt",
  sumario: "sumario.txt",
  hino: "hino.txt",
  referencias: "referencias.txt",
  contracapa: "contracapa.txt",
  conteudo: "base.txt",
};

export const ALLOWED_PROMPT_FILENAMES = new Set<string>([
  ...Object.values(PROMPT_FILES),
  "_shared_rules.txt",
  "classificador.txt",
]);

export type PromptSnapshot = Record<string, string>;

export function sanitizePromptOverrides(raw: unknown): PromptSnapshot {
  if (!raw || typeof raw !== "object") return {};
  const cleaned: PromptSnapshot = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const name = key.trim();
    if (!ALLOWED_PROMPT_FILENAMES.has(name)) continue;
    if (typeof value !== "string") continue;
    cleaned[name] = value;
  }
  return cleaned;
}

export class PromptRouter {
  private readonly windowStart: number;
  private readonly windowEnd: number;
  private readonly overrides: PromptSnapshot;
  private readonly cache = new Map<string, string>();
  private readonly sharedRules: string;

  constructor(
    overrides: PromptSnapshot,
    options?: { windowStart?: number; windowEnd?: number },
  ) {
    this.overrides = sanitizePromptOverrides(overrides);
    this.windowStart = Math.max(1, options?.windowStart ?? 20);
    this.windowEnd = Math.max(0, options?.windowEnd ?? 15);
    this.sharedRules = this.readFile("_shared_rules.txt");
  }

  shouldClassify(pageNumber: number, totalPages: number): boolean {
    if (totalPages <= 0 || pageNumber <= 0) return false;
    const inStart = pageNumber <= this.windowStart;
    const inEnd = pageNumber >= totalPages - this.windowEnd + 1;
    return inStart || inEnd;
  }

  normalizePageType(raw: string): PageType {
    let cleaned = (raw || "").trim().toLowerCase();
    cleaned = cleaned.split(/\s+/)[0] ?? "";
    cleaned = cleaned.replace(/[.,;:!?"']+/g, "");
    if ((PAGE_TYPES as readonly string[]).includes(cleaned)) {
      return cleaned as PageType;
    }
    return CONTENT_PAGE_TYPE;
  }

  static supportsFigureDescription(pageType: string): boolean {
    return (pageType || "").trim().toLowerCase() === CONTENT_PAGE_TYPE;
  }

  static shouldSkipFigurePipeline(pageType: string): boolean {
    return !PromptRouter.supportsFigureDescription(pageType);
  }

  resolvePageType(
    pageNumber: number,
    totalPages: number,
    classifiedType: string | null | undefined,
    mioloOnly = false,
  ): PageType {
    if (mioloOnly) return CONTENT_PAGE_TYPE;
    if (!this.shouldClassify(pageNumber, totalPages)) return CONTENT_PAGE_TYPE;
    if (classifiedType == null) return CONTENT_PAGE_TYPE;
    return this.normalizePageType(classifiedType);
  }

  getPrompt(pageType: string): { prompt: string; promptFile: string } {
    const normalized = this.normalizePageType(pageType);
    const filename = PROMPT_FILES[normalized] ?? "base.txt";
    const cacheKey = `${filename}:${normalized}`;
    if (this.cache.has(cacheKey)) {
      return { prompt: this.cache.get(cacheKey)!, promptFile: filename };
    }

    let prompt = this.readFile(filename);
    if (!prompt && normalized !== CONTENT_PAGE_TYPE) {
      prompt = this.readFile("base.txt");
    }
    if (!prompt) {
      throw new Error(`Prompt ausente no snapshot: ${filename}`);
    }
    prompt = prompt.replaceAll("{{SHARED_RULES}}", this.sharedRules).trim();
    this.cache.set(cacheKey, prompt);
    return { prompt, promptFile: filename };
  }

  get classifierPrompt(): string {
    const prompt = this.readFile("classificador.txt");
    if (!prompt) {
      throw new Error("Prompt ausente no snapshot: classificador.txt");
    }
    return prompt;
  }

  private readFile(filename: string): string {
    const value = this.overrides[filename];
    return typeof value === "string" ? value.trim() : "";
  }
}
