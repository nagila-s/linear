/** Converte ISBN-10 para ISBN-13 (prefixo 978). */
export function convertIsbn10ToIsbn13(isbn10: string): string {
  const isbn = isbn10.replace(/[^0-9X]/gi, "").toUpperCase();
  if (isbn.length !== 10) {
    throw new Error("ISBN-10 inválido");
  }
  const core = `978${isbn.slice(0, 9)}`;
  let sum = 0;
  for (let i = 0; i < 12; i += 1) {
    sum += Number(core[i]) * (i % 2 === 0 ? 1 : 3);
  }
  const check = (10 - (sum % 10)) % 10;
  return `${core}${check}`;
}

/** Converte ISBN-13 (978…) para ISBN-10; se não for 978, devolve o valor original. */
export function convertIsbn13ToIsbn10(isbn13: string): string {
  const isbn = isbn13.replace(/[^0-9]/g, "");
  if (isbn.length !== 13 || !isbn.startsWith("978")) {
    return isbn13;
  }
  const nine = isbn.slice(3, 12);
  let sum = 0;
  for (let i = 0; i < 9; i += 1) {
    sum += Number(nine[i]) * (10 - i);
  }
  const check = (11 - (sum % 11)) % 11;
  const checkChar = check === 10 ? "X" : String(check);
  return `${nine}${checkChar}`;
}
