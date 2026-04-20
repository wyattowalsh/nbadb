import type { NextResponse } from "next/server";

export const ADMIN_SESSION_COOKIE_NAME = "nbadb-admin-session";
export const ADMIN_SESSION_MAX_AGE_SECONDS = 86_400;

const ADMIN_SESSION_MAX_AGE_MS = ADMIN_SESSION_MAX_AGE_SECONDS * 1000;

function timingSafeEqual(a: string, b: string): boolean {
  const maxLen = Math.max(a.length, b.length);
  const paddedA = a.padEnd(maxLen, "\0");
  const paddedB = b.padEnd(maxLen, "\0");
  let result = a.length ^ b.length;
  for (let i = 0; i < maxLen; i++) {
    result |= paddedA.charCodeAt(i) ^ paddedB.charCodeAt(i);
  }
  return result === 0;
}

async function hmacSign(value: string, secret: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(value));
  return Array.from(new Uint8Array(sig))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export async function createAdminSessionToken(
  secret: string,
  now = Date.now(),
): Promise<string> {
  const timestamp = String(now);
  const mac = await hmacSign(timestamp, secret);
  return `${timestamp}.${mac}`;
}

export async function isValidAdminSession(
  cookie: string,
  secret: string,
  now = Date.now(),
): Promise<boolean> {
  const dotIndex = cookie.indexOf(".");
  if (dotIndex === -1) {
    return false;
  }

  const timestamp = cookie.slice(0, dotIndex);
  const mac = cookie.slice(dotIndex + 1);
  const age = now - Number(timestamp);
  if (Number.isNaN(age) || age < 0 || age > ADMIN_SESSION_MAX_AGE_MS) {
    return false;
  }

  const expected = await hmacSign(timestamp, secret);
  return timingSafeEqual(mac, expected);
}

function isProductionCookie() {
  return process.env.NODE_ENV === "production";
}

export function setAdminSessionCookie(
  response: NextResponse,
  value: string,
): void {
  response.cookies.set(ADMIN_SESSION_COOKIE_NAME, value, {
    httpOnly: true,
    sameSite: "lax",
    secure: isProductionCookie(),
    path: "/",
    maxAge: ADMIN_SESSION_MAX_AGE_SECONDS,
  });
}

export function clearAdminSessionCookie(response: NextResponse): void {
  response.cookies.set(ADMIN_SESSION_COOKIE_NAME, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: isProductionCookie(),
    path: "/",
    maxAge: 0,
  });
}
