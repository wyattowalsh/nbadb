import { type NextRequest, NextResponse } from "next/server";
import {
  createAdminSessionToken,
  setAdminSessionCookie,
} from "@/lib/admin/session";

/* ------------------------------------------------------------------ */
/*  Rate limiter (in-memory, per-process)                             */
/* ------------------------------------------------------------------ */
const failedLoginAttempts = new Map<
  string,
  { failures: number; resetAt: number }
>();
const ALLOWED_FAILED_PASSWORDS_PER_WINDOW = 5;
const WINDOW_MS = 15 * 60 * 1000; // 15 minutes
const MAX_TRACKED_KEYS = 10_000;
const SHARED_RATE_LIMIT_BUCKET = "shared-process";

function firstNonEmpty(...values: Array<string | null | undefined>) {
  for (const value of values) {
    const normalized = value?.trim();
    if (normalized) return normalized;
  }
  return null;
}

function firstForwardedIp(value: string | null) {
  return firstNonEmpty(value?.split(",")[0]);
}

function getTrustedProxyIp(request: NextRequest) {
  const headers = request.headers;

  if (process.env.CF_PAGES === "1") {
    return firstNonEmpty(
      headers.get("cf-connecting-ip"),
      headers.get("true-client-ip"),
      headers.get("x-real-ip"),
      firstForwardedIp(headers.get("x-forwarded-for")),
    );
  }

  if (process.env.VERCEL === "1") {
    return firstNonEmpty(
      firstForwardedIp(headers.get("x-forwarded-for")),
      headers.get("x-real-ip"),
    );
  }

  if (process.env.FLY_APP_NAME) {
    return firstNonEmpty(
      headers.get("fly-client-ip"),
      firstForwardedIp(headers.get("x-forwarded-for")),
    );
  }

  return null;
}

function getRateLimitKey(request: NextRequest) {
  const trustedIp = getTrustedProxyIp(request);

  // If we cannot prove a trusted proxy supplied the address, use a shared
  // per-process bucket instead of pretending spoofable client headers are safe.
  return trustedIp ? `ip:${trustedIp}` : SHARED_RATE_LIMIT_BUCKET;
}

function pruneExpiredAttempts(now: number) {
  if (failedLoginAttempts.size < MAX_TRACKED_KEYS) return;

  // Prune expired entries to prevent unbounded growth
  for (const [key, value] of failedLoginAttempts) {
    if (now >= value.resetAt) failedLoginAttempts.delete(key);
  }
}

function getAttemptWindow(key: string, now = Date.now()) {
  pruneExpiredAttempts(now);

  const entry = failedLoginAttempts.get(key);
  if (!entry) return null;
  if (now >= entry.resetAt) {
    failedLoginAttempts.delete(key);
    return null;
  }

  return entry;
}

function getRateLimitStatus(key: string, now = Date.now()) {
  const entry = getAttemptWindow(key, now);
  // Allow up to 5 bad passwords in the current window; the next request is
  // blocked until the window resets.
  if (!entry || entry.failures < ALLOWED_FAILED_PASSWORDS_PER_WINDOW) {
    return { limited: false, retryAfterSeconds: 0 };
  }

  return {
    limited: true,
    retryAfterSeconds: Math.max(1, Math.ceil((entry.resetAt - now) / 1000)),
  };
}

function recordFailedAttempt(key: string, now = Date.now()) {
  const entry = getAttemptWindow(key, now);
  if (!entry) {
    failedLoginAttempts.set(key, { failures: 1, resetAt: now + WINDOW_MS });
    return;
  }

  entry.failures += 1;
}

function clearFailedAttempts(key: string) {
  failedLoginAttempts.delete(key);
}

/* ------------------------------------------------------------------ */
/*  Timing-safe password comparison via HMAC                          */
/* ------------------------------------------------------------------ */
async function timingSafePasswordEqual(
  input: string,
  expected: string,
): Promise<boolean> {
  const enc = new TextEncoder();
  // We only need equal-length digests for constant-time comparison here;
  // the fixed HMAC key is not being used for secrecy.
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode("nbadb-password-compare"),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

  const [sigA, sigB] = await Promise.all([
    crypto.subtle.sign("HMAC", key, enc.encode(input)),
    crypto.subtle.sign("HMAC", key, enc.encode(expected)),
  ]);

  const a = new Uint8Array(sigA);
  const b = new Uint8Array(sigB);

  // Both are 32-byte SHA-256 digests — always same length.
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a[i] ^ b[i];
  }
  return result === 0;
}

function jsonResponse(body: object, init?: ResponseInit) {
  const response = NextResponse.json(body, init);
  response.headers.set("Cache-Control", "no-store");
  return response;
}

/* ------------------------------------------------------------------ */
/*  POST handler                                                      */
/* ------------------------------------------------------------------ */
export async function POST(request: NextRequest) {
  const password = process.env.ADMIN_PASSWORD;

  if (!password) {
    return jsonResponse(
      {
        error: "Admin auth is unavailable until ADMIN_PASSWORD is configured.",
      },
      { status: 503 },
    );
  }

  const rateLimitKey = getRateLimitKey(request);
  const { limited, retryAfterSeconds } = getRateLimitStatus(rateLimitKey);

  if (limited) {
    return jsonResponse(
      { error: "Too many login attempts. Try again later." },
      {
        status: 429,
        headers: { "Retry-After": String(retryAfterSeconds) },
      },
    );
  }

  let body: { password?: string };
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "Invalid request body" }, { status: 400 });
  }

  if (
    typeof body.password !== "string" ||
    !(await timingSafePasswordEqual(body.password, password))
  ) {
    recordFailedAttempt(rateLimitKey);
    return jsonResponse({ error: "Invalid password" }, { status: 401 });
  }

  clearFailedAttempts(rateLimitKey);

  const cookieValue = await createAdminSessionToken(password);
  const response = jsonResponse({ ok: true });
  setAdminSessionCookie(response, cookieValue);

  return response;
}
