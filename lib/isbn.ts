export function normalizeIsbn(value: string): string {
  return value.replace(/[^0-9Xx]/g, "").toUpperCase();
}

export function isValidIsbn10(raw: string): boolean {
  const isbn = normalizeIsbn(raw);
  if (!/^\d{9}[\dX]$/.test(isbn)) return false;
  const sum = isbn.split("").reduce((acc, char, index) => {
    const value = char === "X" ? 10 : Number(char);
    return acc + value * (10 - index);
  }, 0);
  return sum % 11 === 0;
}

export function isValidIsbn13(raw: string): boolean {
  const isbn = normalizeIsbn(raw);
  if (!/^\d{13}$/.test(isbn)) return false;
  const sum = isbn
    .slice(0, 12)
    .split("")
    .reduce((acc, char, index) => acc + Number(char) * (index % 2 === 0 ? 1 : 3), 0);
  const checkDigit = (10 - (sum % 10)) % 10;
  return checkDigit === Number(isbn[12]);
}

export function isValidIsbn(raw: string): boolean {
  return isValidIsbn10(raw) || isValidIsbn13(raw);
}

export function extractIsbnFromFilename(filename: string): string | null {
  const base = filename.replace(/\.pdf$/i, "").trim();
  if (!/^\d{10}$|^\d{13}$/.test(base)) return null;
  return base;
}

/** Identificador do livro: ISBN informado, ISBN no nome do arquivo ou slug do arquivo. */
export function resolveBookKey(isbnInput: string, filename: string): string {
  const trimmed = isbnInput.trim();
  if (trimmed) {
    const normalized = normalizeIsbn(trimmed);
    if (isValidIsbn(normalized)) return normalized;
  }

  const fromFile = extractIsbnFromFilename(filename);
  if (fromFile && isValidIsbn(fromFile)) return fromFile;

  const stem = filename.replace(/\.pdf$/i, "").trim();
  const slug = stem
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

  return slug || "livro";
}
