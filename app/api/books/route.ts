import { NextResponse } from "next/server";

/** A API FastAPI ainda não expõe listagem de livros; retorno vazio até existir endpoint. */
export async function GET(): Promise<NextResponse> {
  return NextResponse.json({
    books: [],
    message:
      "Listagem de livros processados ainda não está na API Python. Use o fluxo de upload na tela principal.",
  });
}
