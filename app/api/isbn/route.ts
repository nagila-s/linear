import { NextRequest, NextResponse } from "next/server";
import { NotFoundError } from "@/lib/cbl/errors";
import { searchInCbl } from "@/lib/cbl/searchInCbl";
import { jsonError } from "@/app/api/_utils/fastapi";
import { isValidIsbn, normalizeIsbn } from "@/lib/isbn";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const raw = request.nextUrl.searchParams.get("isbn")?.trim();
  if (!raw) return jsonError("ISBN não informado.", 400);

  const isbn = normalizeIsbn(raw);
  if (!isValidIsbn(isbn)) {
    return jsonError("ISBN inválido.", 400);
  }

  try {
    const book = await searchInCbl(isbn);
    return NextResponse.json({
      found: true,
      isbn: book.isbn,
      title: book.title,
      authors: book.authors,
      publisher: book.publisher,
      metadata: {
        title: book.title,
        subtitle: book.subtitle,
        authors: book.authors,
        publisher: book.publisher,
        year: book.year,
        synopsis: book.synopsis,
        provider: book.provider,
      },
    });
  } catch (error) {
    if (error instanceof NotFoundError) {
      return NextResponse.json({
        found: false,
        isbn,
        message: "ISBN não encontrado.",
      });
    }
    return jsonError("Falha ao consultar a CBL.", 502);
  }
}
