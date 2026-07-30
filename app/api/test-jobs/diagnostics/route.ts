import { NextResponse } from "next/server";
import { describeSupabaseUrl } from "@/lib/supabase-admin";
import { jsonError, requireSession } from "@/app/api/test-jobs/_utils";

/** Diagnostico sem vazar segredos: so formato/tamanho das variaveis. */
export async function GET(): Promise<NextResponse> {
  const auth = await requireSession();
  if (!auth.ok) return auth.response;

  try {
    const rawUrl = process.env.SUPABASE_URL;
    const rawKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
    const url = describeSupabaseUrl(rawUrl);

    return NextResponse.json({
      supabase_url: {
        present: Boolean(rawUrl && rawUrl.length),
        length: rawUrl?.length ?? 0,
        starts_with: rawUrl?.slice(0, 12) ?? "",
        has_quotes: Boolean(rawUrl && /^["']|["']$/.test(rawUrl.trim())),
        has_whitespace: Boolean(rawUrl && /\s/.test(rawUrl.trim())),
        valid: url.ok,
        reason: url.reason ?? null,
        host: url.host ?? null,
      },
      service_role_key: {
        present: Boolean(rawKey && rawKey.length),
        length: rawKey?.length ?? 0,
        has_quotes: Boolean(rawKey && /^["']|["']$/.test(rawKey.trim())),
      },
      session_secret_present: Boolean(process.env.SESSION_SECRET?.trim()),
      node_env: process.env.NODE_ENV ?? null,
      vercel_env: process.env.VERCEL_ENV ?? null,
    });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Falha no diagnostico.", 500);
  }
}
