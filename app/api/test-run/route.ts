/**
 * LEGADO — não usado pela área de testes.
 *
 * A UI em /testes agora usa /api/test-jobs (fila exclusiva no Supabase + Edge Functions).
 * Este endpoint encaminhava PDF para a FastAPI síncrona (/jobs/test-run), que depende
 * de Poppler na imagem da API e do worker AWS. Mantido só para compatibilidade temporária.
 */
import { NextRequest, NextResponse } from "next/server";
import { jsonError } from "@/app/api/_utils/fastapi";

export const maxDuration = 30;

export async function POST(_request: NextRequest): Promise<NextResponse> {
  return jsonError(
    "Endpoint legado. Use a area de testes em /testes (fila Supabase /api/test-jobs).",
    410,
  );
}
