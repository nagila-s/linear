import { NextResponse } from "next/server";
import { jsonError } from "@/app/api/_utils/fastapi";

export async function GET(): Promise<NextResponse> {
  return jsonError(
    "Download por livro ainda não está na API Python. Baixe o JSON pelo modal após o processamento.",
    501,
  );
}
