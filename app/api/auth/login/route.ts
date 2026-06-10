import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { SESSION_COOKIE_NAME } from "@/lib/auth";

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

  const token = crypto.randomBytes(24).toString("hex");
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
