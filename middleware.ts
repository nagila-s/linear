import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME } from "@/lib/auth";

const PUBLIC_PATHS = ["/login", "/api/auth/login", "/_next", "/favicon.ico"];

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.some((path) => pathname.startsWith(path))) {
    return NextResponse.next();
  }

  if (!request.cookies.get(SESSION_COOKIE_NAME)?.value) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!.*\\..*).*)"],
};
