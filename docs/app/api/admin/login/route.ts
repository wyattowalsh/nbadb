import { type NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "nbadb-admin-session";

/* ------------------------------------------------------------------ */
/*  Rate limiter (in-memory, per-process)                             */
/* ------------------------------------------------------------------ */
const loginAttempts = new Map<string, { count: number; resetAt: number }>();
const MAX_ATTEMPTS = 5;
const WINDOW_MS = 15 * 60 * 1000; // 15 minutes

function isRateLimited(ip: string): boolean {
  const now = Date.now();
  const entry = loginAttempts.get(ip);

  if (!entry || now > entry.resetAt) {
    loginAttempts.set(ip, { count: 1, resetAt: now + WINDOW_MS });
    return false;
  }

  entry.count += 1;
  return entry.count > MAX_ATTEMPTS;
}

/* ------------------------------------------------------------------ */
/*  Timing-safe password comparison via HMAC                          */
/* ------------------------------------------------------------------ */
async function timingSafePasswordEqual(
  input: string,
  expected: string,
): Promise<boolean> {
  const enc = new TextEncoder();
  // Use a fixed key derived from the expected password itself — we only
  // need the constant-time property of HMAC comparison, not secrecy of
  // the key.  Both sides are HMACed with the same key so the digests
  // match iff the inputs match, regardless of length.
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

/* ------------------------------------------------------------------ */
/*  Session token creation                                            */
/* ------------------------------------------------------------------ */
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

/* ------------------------------------------------------------------ */
/*  POST handler                                                      */
/* ------------------------------------------------------------------ */
export async function POST(request: NextRequest) {
  const password = process.env.ADMIN_PASSWORD;

  if (!password) {
    return NextResponse.json(
      { error: "No admin password configured" },
      { status: 500 },
    );
  }

  // Rate-limit by IP
  const ip =
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    request.headers.get("x-real-ip") ??
    "unknown";

  if (isRateLimited(ip)) {
    return NextResponse.json(
      { error: "Too many login attempts. Try again later." },
      { status: 429 },
    );
  }

  let body: { password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid request body" },
      { status: 400 },
    );
  }

  if (
    typeof body.password !== "string" ||
    !(await timingSafePasswordEqual(body.password, password))
  ) {
    return NextResponse.json({ error: "Invalid password" }, { status: 401 });
  }

  const timestamp = String(Date.now());
  const mac = await hmacSign(timestamp, password);
  const cookieValue = `${timestamp}.${mac}`;

  const isProduction = process.env.NODE_ENV === "production";

  const response = NextResponse.json({ ok: true });
  response.cookies.set(COOKIE_NAME, cookieValue, {
    httpOnly: true,
    sameSite: "lax",
    secure: isProduction,
    path: "/",
    maxAge: 86_400, // 24 hours
  });

  return response;
}
