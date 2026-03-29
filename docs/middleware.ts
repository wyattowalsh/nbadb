import { type NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "nbadb-admin-session";
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

function timingSafeEqual(a: string, b: string): boolean {
  const maxLen = Math.max(a.length, b.length);
  const paddedA = a.padEnd(maxLen, "\0");
  const paddedB = b.padEnd(maxLen, "\0");
  let result = a.length ^ b.length; // non-zero if lengths differ
  for (let i = 0; i < maxLen; i++) {
    result |= paddedA.charCodeAt(i) ^ paddedB.charCodeAt(i);
  }
  return result === 0;
}

async function hmacSign(timestamp: string, secret: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(timestamp));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function isValidSession(
  cookie: string,
  secret: string,
): Promise<boolean> {
  const dotIndex = cookie.indexOf(".");
  if (dotIndex === -1) return false;

  const timestamp = cookie.slice(0, dotIndex);
  const mac = cookie.slice(dotIndex + 1);

  const age = Date.now() - Number(timestamp);
  if (Number.isNaN(age) || age < 0 || age > 86_400_000) return false;

  const expected = await hmacSign(timestamp, secret);
  return timingSafeEqual(mac, expected);
}

export async function middleware(request: NextRequest) {
  const pathname = normalizePathname(request.nextUrl.pathname);
  const password = process.env.ADMIN_PASSWORD;

  if (PUBLIC_ADMIN_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  if (!password) {
    if (pathname.startsWith("/api/admin")) {
      return NextResponse.json(
        { error: "Admin not configured" },
        { status: 503 },
      );
    }
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/admin/login";
    return NextResponse.redirect(loginUrl);
  }

  const cookie = request.cookies.get(COOKIE_NAME)?.value;

  if (cookie && (await isValidSession(cookie, password))) {
    return NextResponse.next();
  }

  if (pathname.startsWith("/api/admin")) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/admin/login";
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/admin/:path*", "/api/admin/:path*"],
};
