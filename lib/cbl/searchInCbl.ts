import { NotFoundError } from "@/lib/cbl/errors";
import { convertIsbn10ToIsbn13, convertIsbn13ToIsbn10 } from "@/lib/cbl/isbn-tools";

const API_BASE_URL =
  "https://isbn-search-br.search.windows.net/indexes/isbn-index/docs";
const API_SEARCH_URL = `${API_BASE_URL}/search?api-version=2016-09-01`;

/** Mesma chave do site oficial da CBL (base64 para não expor em texto claro). */
const API_BASE64_KEY = "MTAwMjE2QTIzQzVBRUUzOTAzMzhCQkQxOUVBODZEMjk=";
const API_KEY = Buffer.from(API_BASE64_KEY, "base64").toString("utf-8");

type CblDimensions = {
  width: number;
  height: number;
  unit: "CENTIMETER";
} | null;

export type CblBookResult = {
  isbn: string;
  title: string;
  subtitle: string | null;
  authors: string[];
  publisher: string;
  synopsis: string | null;
  dimensions: CblDimensions;
  year: number | null;
  format: "PHYSICAL" | "DIGITAL";
  page_count: number | null;
  subjects: string[];
  location: string | null;
  retail_price: null;
  cover_url: null;
  provider: "cbl";
};

function parseDimensions(dimensionsStr: string | null | undefined): CblDimensions {
  const dimensions = dimensionsStr
    ? dimensionsStr.match(/(\d{2})(\d)?x(\d{2})(\d)?$/)
    : null;

  if (!dimensions) {
    return null;
  }

  return {
    width: parseFloat(dimensions[1] + (dimensions[2] ? `.${dimensions[2]}` : "")),
    height: parseFloat(dimensions[3] + (dimensions[4] ? `.${dimensions[4]}` : "")),
    unit: "CENTIMETER",
  };
}

function parseLocation(city: string | null | undefined, state: string | null | undefined): string | null {
  if (!city || !state || city.length === 0 || state.length === 0) {
    return null;
  }
  return `${city}, ${state}`;
}

function normalizeAuthors(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.map(String).filter(Boolean);
  }
  if (typeof raw === "string" && raw.trim()) {
    return raw
      .split(/[;,]/)
      .map((part) => part.trim())
      .filter(Boolean);
  }
  return [];
}

type CblIndexRow = {
  RowKey?: string;
  Title?: string;
  Subtitle?: string;
  Authors?: unknown;
  Imprint?: string;
  Sinopse?: string;
  Dimensao?: string;
  Ano?: string;
  Formato?: string;
  Paginas?: string;
  Subject?: string;
  PalavrasChave?: string[];
  Cidade?: string;
  UF?: string;
};

/**
 * Busca metadados do livro na base da CBL (Azure Search).
 */
export async function searchInCbl(isbn: string): Promise<CblBookResult> {
  const digits = isbn.replace(/[^0-9X]/gi, "").toUpperCase();
  const isbn13 = digits.length === 10 ? convertIsbn10ToIsbn13(digits) : digits;
  const isbn10 = digits.length === 13 ? convertIsbn13ToIsbn10(digits) : digits;

  const searchPayload = {
    count: true,
    facets: ["Imprint,count:50", "Authors,count:50"],
    filter: "",
    orderby: null,
    queryType: "full",
    search: `${isbn13} OR ${isbn10}`,
    searchFields: "FormattedKey,RowKey",
    searchMode: "any",
    select: "*",
    skip: 0,
    top: 12,
  };

  try {
    const response = await fetch(API_SEARCH_URL, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Api-Key": API_KEY,
      },
      body: JSON.stringify(searchPayload),
      signal: AbortSignal.timeout(5000),
    });

    if (!response.ok) {
      throw new NotFoundError();
    }

    const data = (await response.json()) as { value?: CblIndexRow[] };
    if (!data.value?.[0]) {
      throw new NotFoundError();
    }

    const cblBook = data.value[0];

    return {
      isbn: cblBook.RowKey ?? isbn13,
      title: cblBook.Title ?? "",
      subtitle: cblBook.Subtitle ?? null,
      authors: normalizeAuthors(cblBook.Authors),
      publisher: cblBook.Imprint ?? "",
      synopsis: cblBook.Sinopse ?? null,
      dimensions: parseDimensions(cblBook.Dimensao),
      year: cblBook.Ano ? parseInt(cblBook.Ano, 10) : null,
      format: cblBook.Formato === "Papel" ? "PHYSICAL" : "DIGITAL",
      page_count: cblBook.Paginas ? parseInt(cblBook.Paginas, 10) : null,
      subjects: [cblBook.Subject]
        .concat(cblBook.PalavrasChave ?? [])
        .filter((item): item is string => Boolean(item)),
      location: parseLocation(cblBook.Cidade, cblBook.UF),
      retail_price: null,
      cover_url: null,
      provider: "cbl",
    };
  } catch (error) {
    if (error instanceof NotFoundError) {
      throw error;
    }
    // eslint-disable-next-line no-console
    console.error("[cbl] Error fetching ISBN:", {
      isbn,
      error: error instanceof Error ? error.message : error,
    });
    throw new NotFoundError();
  }
}
