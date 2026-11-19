import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME } from "@/lib/auth";
import { verifySignedSessionToken } from "@/lib/session";
import {
  MAINTENANCE_HEADERS,
  MAINTENANCE_HTML,
  MAINTENANCE_JSON,
  isMaintenanceMode,
} from "@/lib/maintenance";

const PUBLIC_PATHS = ["/login", "/api/auth/login", "/_next", "/favicon.ico"];

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const { pathname } = request.nextUrl;

  // Manutenção vem antes de tudo: nem login, nem API, nem sessão válida passam.
  if (isMaintenanceMode()) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json(MAINTENANCE_JSON, { status: 503, headers: MAINTENANCE_HEADERS });
    }
    return new NextResponse(MAINTENANCE_HTML, {
      status: 503,
      headers: { ...MAINTENANCE_HEADERS, "Content-Type": "text/html; charset=utf-8" },
    });
  }

  if (PUBLIC_PATHS.some((path) => pathname.startsWith(path))) {
    return NextResponse.next();
  }

  const token = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!(await verifySignedSessionToken(token))) {
    // API precisa de JSON 401 — redirect HTML fazia o fetch do cliente quebrar no .json().
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "Sessao invalida ou expirada." }, { status: 401 });
    }
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!.*\\..*).*)"],
};
