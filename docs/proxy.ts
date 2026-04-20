import { type NextRequest, NextResponse } from "next/server";
import {
  ADMIN_SESSION_COOKIE_NAME,
  isValidAdminSession,
} from "@/lib/admin/session";

const PUBLIC_ADMIN_PATHS = new Set([
  "/admin/login",
  "/api/admin/login",
  "/api/admin/logout",
]);

function normalizePathname(pathname: string): string {
  if (pathname.length > 1 && pathname.endsWith("/")) {
    return pathname.slice(0, -1);
  }
  return pathname;
}

function jsonResponse(body: object, status: number) {
  const response = NextResponse.json(body, { status });
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export async function proxy(request: NextRequest) {
  const pathname = normalizePathname(request.nextUrl.pathname);
  const password = process.env.ADMIN_PASSWORD;
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/admin/login";

  if (!password) {
    if (pathname.startsWith("/api/admin")) {
      return jsonResponse(
        {
          error:
            "Admin auth is unavailable until ADMIN_PASSWORD is configured.",
        },
        503,
      );
    }

    if (pathname === "/admin/login") {
      return NextResponse.next();
    }

    return NextResponse.redirect(loginUrl);
  }

  if (PUBLIC_ADMIN_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  const cookie = request.cookies.get(ADMIN_SESSION_COOKIE_NAME)?.value;

  if (cookie && (await isValidAdminSession(cookie, password))) {
    return NextResponse.next();
  }

  if (pathname.startsWith("/api/admin")) {
    return jsonResponse({ error: "Unauthorized" }, 401);
  }

  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/admin/:path*", "/api/admin/:path*"],
};
