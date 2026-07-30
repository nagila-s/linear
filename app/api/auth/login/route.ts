import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME } from "@/lib/auth";
import { createSignedSessionToken } from "@/lib/session";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const { password } = (await request.json()) as { password?: string };
  const allowedPasswords = [
    process.env.ACCESS_PASSWORD?.trim(),
    process.env.APP_PASSWORD?.trim(),
  ].filter((value): value is string => Boolean(value));

  if (!allowedPasswords.length) {
    return NextResponse.json(
      { error: "ACCESS_PASSWORD (ou APP_PASSWORD) nao configurada no ambiente." },
      { status: 500 },
    );
  }

  if (!password || !allowedPasswords.includes(password)) {
    return NextResponse.json({ error: "Senha invalida." }, { status: 401 });
  }

  let token: string;
  try {
    token = await createSignedSessionToken("linear-user");
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Falha ao criar sessao." },
      { status: 500 },
    );
  }

  const response = NextResponse.json({ token });
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24,
  });

  return response;
}
