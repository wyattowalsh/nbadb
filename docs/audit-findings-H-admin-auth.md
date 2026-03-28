# Audit H: Admin Auth + Shell

**Auditor:** Claude Opus 4.6
**Date:** 2026-03-28
**Method:** Source code review of middleware, API routes, login page, admin shell + live HTTP testing (fetcher against running dev server on port 3001)
**Files reviewed:** `middleware.ts`, `app/api/admin/login/route.ts`, `app/api/admin/logout/route.ts`, `app/api/admin/health/route.ts`, `app/(admin)/admin/login/page.tsx`, `app/(admin)/admin/layout.tsx`, `components/admin/admin-shell.tsx`, `components/admin/admin-nav.tsx`, `app/robots.ts`, `app/layout.tsx`

---

## Authentication Flow

### Unauthenticated Access

**Test:** Fetched `http://localhost:3001/admin` without any session cookie.

**Expected:** HTTP 307 redirect to `/admin/login`.

**Actual:** HTTP 200 with full dashboard HTML rendered (title "Control Center | nbadb", subsystem status data, content counts).

**Root cause:** The `ADMIN_PASSWORD` environment variable is defined in the repo-root `.env` file, but the Next.js dev server runs from the `docs/` subdirectory. Next.js only loads `.env` files from its project root (`docs/`), so `process.env.ADMIN_PASSWORD` is `undefined` in the server process. Middleware line 49 (`if (!password) return NextResponse.next()`) passes all requests through.

**Impact (DEFECT H1, Severity: High):** When `ADMIN_PASSWORD` is not loaded by the Next.js runtime, the entire admin surface -- all pages and all `/api/admin/*` endpoints -- is publicly accessible with no authentication. This was also flagged as D16 in Audit I, but the live test here confirms the issue is actively exploitable in the current dev configuration.

**Secondary test:** Fetched `http://localhost:3001/api/admin/health` without auth.

**Actual:** HTTP 200 with full JSON response: `{"overall":"unknown","subsystems":{"build":{"status":"healthy","detail":"49 pages indexed"},...},"pageCount":49,"lastBuild":null}`. The endpoint should have returned `{"error":"Unauthorized"}` with HTTP 401.

### Login Form

**Source review of `app/(admin)/admin/login/page.tsx`:**

1. **Form structure:** Clean single-field password form with `<label htmlFor="password">`, `type="password"`, `autoFocus`, `required`. Accessibility is correct.
2. **Error handling:** Wrong password shows a styled error message from the API (`data.error ?? "Invalid password"`). Network errors show "Connection failed". Loading state disables the submit button and shows "Signing in...".
3. **Success flow:** On successful login, calls `router.push("/admin")` followed by `router.refresh()`. The refresh is necessary to re-run server components with the new cookie.

**Source review of `app/api/admin/login/route.ts`:**

4. **Password comparison (DEFECT H2, Severity: Medium):** The login API at line 40 uses a direct string comparison (`body.password !== password`) for the submitted password. This is **not timing-safe**. While the HMAC cookie verification in middleware uses `timingSafeEqual`, the initial password submission does not. An attacker with network timing precision could theoretically extract the password character-by-character. The login endpoint should use the same `timingSafeEqual` function (or `crypto.timingSafeEqual` from Node.js).

5. **Missing ADMIN_PASSWORD handling:** When `ADMIN_PASSWORD` is unset, the login API correctly returns HTTP 500 with `{"error":"No admin password configured"}`. This is good -- the login API fails closed, unlike the middleware which fails open.

6. **No rate limiting (DEFECT H3, Severity: Medium):** There is no rate limiting, account lockout, or exponential backoff on the login endpoint. An attacker can submit unlimited password attempts at machine speed. For a single shared password, this makes brute-force attacks trivial against short or weak passwords.

7. **No CSRF protection (DEFECT H4, Severity: Low):** The login POST endpoint has no CSRF token validation. Since the login form only accepts a password (no username), and the cookie uses `SameSite: lax`, the practical CSRF risk is low -- an attacker would need to know the password to forge a useful login. However, the logout endpoint (also POST, no CSRF) could be targeted to force-logout an authenticated admin.

### Session Management

**Cookie properties (from `app/api/admin/login/route.ts` lines 54-60):**

| Property | Value | Assessment |
|----------|-------|------------|
| `httpOnly` | `true` | Correct -- prevents JS access |
| `sameSite` | `"lax"` | Correct -- prevents CSRF from cross-origin POSTs |
| `secure` | `isProduction` (true when `NODE_ENV=production`) | Correct -- allows dev over HTTP, enforces HTTPS in prod |
| `path` | `"/"` | Acceptable -- cookie sent for all paths |
| `maxAge` | `86_400` (24 hours) | Appropriate session length |

**Cookie format:** `{timestamp}.{hmac_sha256_hex}` where the HMAC signs the timestamp using the admin password as the key.

**Session validation (`middleware.ts` lines 29-43):**

8. **TTL enforcement:** Cookie age is checked against 86,400,000 ms (24h). Negative age (future timestamp) is correctly rejected. `NaN` is correctly rejected. Good.

9. **HMAC verification:** The expected MAC is recomputed from the timestamp and compared using `timingSafeEqual`. Good.

10. **Timing-safe comparison (DEFECT H5, Severity: Low):** The custom `timingSafeEqual` function at line 5-11 has a subtle issue: `if (a.length !== b.length) return false` is an **early return on length mismatch**. Since HMAC hex output is always 64 characters, this is not exploitable in practice (the expected MAC is always the same length). However, it technically breaks the "timing-safe" contract. A more robust implementation would pad or use `crypto.subtle.timingSafeEqual` if available, or use Node.js `crypto.timingSafeEqual` with Buffer conversion.

11. **Cookie name is predictable:** `"nbadb-admin-session"` -- this is standard practice and not a vulnerability, but worth noting for completeness.

12. **No session revocation mechanism:** There is no server-side session store. Once a cookie is issued, it remains valid for 24 hours. There is no way to invalidate a specific session (e.g., if the password is changed). Changing `ADMIN_PASSWORD` invalidates all sessions since the HMAC key changes, which is an acceptable workaround.

### Logout

**Source review of `app/api/admin/logout/route.ts`:**

13. **Cookie clearing:** Sets the cookie to an empty string with `maxAge: 0`, which instructs the browser to delete it immediately. This is correct.

14. **No auth required for logout:** The middleware excludes `/api/admin/logout` from auth checks (line 56). This means anyone can POST to the logout endpoint. Since the response only clears a cookie (it cannot clear another user's cookie due to `httpOnly`), this is harmless. However, it means the logout endpoint always returns 200 even for unauthenticated callers.

15. **Client-side logout:** The `AdminShell` component calls `fetch("/api/admin/logout", { method: "POST" })` then navigates to `/admin/login` with `router.refresh()`. Good flow.

---

## Admin Shell

### Navigation

**Source review of `components/admin/admin-nav.tsx`:**

16. **Nav items:** 5 links -- Overview (`/admin`), Content (`/admin/content`), Pipeline (`/admin/pipeline`), Profiling (`/admin/profiling`), Health (`/admin/health`). Each has a Lucide icon.

17. **Active state detection (line 22-24):** Uses `usePathname()` with exact match for `/admin` and `startsWith` for sub-routes. This is correct -- `/admin/content` does not false-activate the Overview link. Sub-route active states use `startsWith`, so `/admin/pipeline/foo` would correctly highlight the Pipeline link.

18. **Footer actions:** "Back to docs" (`/docs`) and "Sign out" button. Both are in the sidebar footer, separated by a border. The Sign out button triggers the logout API flow.

### Layout

**Source review of `app/(admin)/admin/layout.tsx`:**

19. **Metadata:** Title template is `"%s | Control Center"` with default "Control Center". The `robots` metadata is `{ index: false, follow: false }`, which renders as `<meta name="robots" content="noindex, nofollow"/>` in the HTML head. This correctly tells search engines not to index admin pages.

20. **Robots.txt gap (DEFECT H6, Severity: Low):** While the meta tag says `noindex, nofollow`, the `robots.txt` (generated by `app/robots.ts`) has `Allow: /` with no `Disallow: /admin` rule. Well-behaved crawlers respect the meta tag, but adding an explicit `Disallow: /admin` to `robots.txt` is defense-in-depth.

21. **Shell wrapper:** Uses `<AdminShell>` which provides the sidebar + main content layout. All admin child pages render inside this shell.

### Responsive Behavior

**Source review of `components/admin/admin-shell.tsx`:**

22. **Desktop sidebar:** `<aside className="hidden w-60 shrink-0 border-r ... lg:block">` -- visible only at `lg` breakpoint (1024px+). Fixed 60-unit width with sticky positioning (`sticky top-0 h-screen`). Contains branding, nav, and footer actions.

23. **Mobile sidebar:** Slide-in drawer (`fixed inset-y-0 left-0 z-50 w-60`) controlled by `sidebarOpen` state. Transforms from `-translate-x-full` to `translate-x-0` with `duration-300` transition. An overlay backdrop (`fixed inset-0 z-40 bg-background/80 backdrop-blur-sm`) dismisses the sidebar on click.

24. **Mobile header:** Sticky header (`sticky top-0 z-30`) with hamburger menu button and branding. Only visible below `lg` breakpoint.

25. **Z-index layering:** Mobile header (`z-30`) < overlay backdrop (`z-40`) < mobile sidebar (`z-50`). Correct stacking order.

26. **Content area:** `max-w-7xl` with responsive padding (`px-4 sm:px-6 lg:px-8`). Good content containment.

27. **Keyboard accessibility (DEFECT H7, Severity: Medium):** The mobile sidebar has no focus trap. When the sidebar opens, focus is not moved to the sidebar, and Tab can navigate behind the overlay to the main content. Pressing Escape does not close the sidebar. The overlay `onClick` closes the sidebar, but there is no keyboard equivalent.

28. **Mobile sidebar close button:** The X button inside the mobile sidebar uses `onClick` but has no `aria-label`. Screen readers would announce it as an unlabeled button.

---

## Edge Cases

### Missing ADMIN_PASSWORD

29. **Middleware behavior:** Returns `NextResponse.next()` -- all requests pass through without authentication. This is intentional for dev convenience but dangerous if an operator deploys without the variable. Confirmed via live test: all admin pages and APIs are fully accessible.

30. **Login API behavior:** Returns HTTP 500 with `{"error":"No admin password configured"}`. This is correct -- the login form will show "No admin password configured" to the user, which serves as an implicit warning.

31. **Inconsistency (DEFECT H8, Severity: Medium):** The middleware fails **open** (allows access) while the login API fails **closed** (blocks login). This creates a paradox: when `ADMIN_PASSWORD` is unset, the admin dashboard is accessible without logging in, but the login page shows an error if you try to log in. An operator visiting `/admin/login` would see "No admin password configured" and think admin is disabled, while in reality `/admin` is fully open.

### Expired Session Cookie

32. **TTL check:** `isValidSession` computes `age = Date.now() - Number(timestamp)` and rejects if `age > 86_400_000`. A 25-hour-old cookie would fail validation (age = 90,000,000 > 86,400,000). The middleware would then redirect to `/admin/login` for page requests or return 401 for API requests. This is correct.

33. **Stale cookie in browser:** The cookie has `maxAge: 86_400` (seconds), so the browser should auto-delete it after 24 hours. Even if the browser retains it slightly past expiry, the server-side TTL check provides a second layer of validation. Good defense-in-depth.

### Invalid/Tampered Cookie

34. **No dot separator:** `cookie.indexOf(".")` returns -1, function returns `false`. Correct.

35. **Non-numeric timestamp:** `Number(timestamp)` returns `NaN`, `Date.now() - NaN` is `NaN`, `Number.isNaN(age)` check catches it. Correct.

36. **Tampered HMAC:** The recomputed HMAC won't match the tampered value. `timingSafeEqual` returns `false`. Correct.

37. **Tampered timestamp:** A new HMAC is computed for the tampered timestamp. Since the attacker doesn't know the secret key, the computed HMAC won't match the original MAC in the cookie. Correct.

38. **Empty cookie value:** `cookie.indexOf(".")` returns -1 for empty string. Correct.

39. **Very long cookie value:** No explicit length check, but `hmacSign` will process the timestamp portion regardless of length. `Number()` on a very long string returns `NaN` which is caught. No DoS vector here since `crypto.subtle.sign` is bounded by the key, not the message length (and timestamps are short anyway after the dot split).

---

## Defects

| ID | Severity | Location | Description |
|----|----------|----------|-------------|
| H1 | High | `middleware.ts:49` + deployment | `ADMIN_PASSWORD` in repo-root `.env` is not loaded by Next.js (which reads from `docs/.env`). Middleware fails open, making the entire admin surface publicly accessible. Confirmed via live test. |
| H2 | Medium | `api/admin/login/route.ts:40` | Password comparison uses `!==` (not timing-safe). The middleware's HMAC comparison is timing-safe, but the login endpoint's password check is not. |
| H3 | Medium | `api/admin/login/route.ts` | No rate limiting on login endpoint. Unlimited brute-force attempts possible. |
| H4 | Low | `api/admin/login/route.ts` | No CSRF token on login form. Low practical risk due to `SameSite: lax` cookie. |
| H5 | Low | `middleware.ts:6` | `timingSafeEqual` early-returns on length mismatch, technically breaking the timing-safe contract. Not exploitable for HMAC hex (fixed 64-char length). |
| H6 | Low | `app/robots.ts` | `robots.txt` has no `Disallow: /admin` rule. Meta tag provides `noindex, nofollow` but defense-in-depth is missing. |
| H7 | Medium | `components/admin/admin-shell.tsx:54-59` | Mobile sidebar overlay has no focus trap, no Escape-to-close, and close button has no `aria-label`. |
| H8 | Medium | `middleware.ts:49` vs `api/admin/login/route.ts:22-27` | Middleware fails open (allows access) while login API fails closed (returns 500) when `ADMIN_PASSWORD` is unset. Creates a confusing state where admin is accessible but login appears broken. |

---

## Enhancement Ideas

| ID | Priority | Description |
|----|----------|-------------|
| H-E1 | High | Create a `docs/.env` (or `docs/.env.local`) that loads `ADMIN_PASSWORD`, or use `next.config.mjs` `env` option to explicitly pass it from the parent `.env`. |
| H-E2 | High | Add rate limiting to the login endpoint (e.g., in-memory counter with 5 attempts per IP per minute, or use a middleware-based approach). |
| H-E3 | Medium | Use timing-safe comparison for the password check in the login API route (import the `timingSafeEqual` from middleware or use `crypto.timingSafeEqual`). |
| H-E4 | Medium | Add `Disallow: /admin` and `Disallow: /api/admin` to `robots.txt` as defense-in-depth. |
| H-E5 | Medium | Implement focus trapping and Escape-to-close for the mobile sidebar overlay. Add `aria-label="Close sidebar"` to the X button. |
| H-E6 | Low | Display a warning banner in the admin UI when `ADMIN_PASSWORD` is not configured (detectable via a client-side fetch to a status endpoint or a build-time flag). |
| H-E7 | Low | Add `Disallow: /admin` to `robots.txt` for defense-in-depth alongside the `noindex` meta tag. |
| H-E8 | Low | Consider adding a session revocation mechanism (e.g., a server-side nonce stored in a file/env that's included in the HMAC, allowing bulk invalidation by changing the nonce). |

---

## Notes

1. **The HMAC session cookie scheme is well-designed.** Using `timestamp.hmac(timestamp, password)` is a compact, stateless approach. The 24-hour TTL is enforced both client-side (cookie `maxAge`) and server-side (timestamp age check). The HMAC uses SHA-256 via Web Crypto API, which is correct and performant.

2. **The `hmacSign` function is duplicated** between `middleware.ts` and `app/api/admin/login/route.ts`. Both implementations are identical. This should be extracted to a shared utility to prevent drift.

3. **The `COOKIE_NAME` constant is duplicated** across `middleware.ts`, `app/api/admin/login/route.ts`, and `app/api/admin/logout/route.ts` (all set to `"nbadb-admin-session"`). Should be a shared constant.

4. **The admin layout correctly sets `robots: { index: false, follow: false }`**, which Next.js renders as `<meta name="robots" content="noindex, nofollow"/>`. This was confirmed in the live-fetched HTML from the earlier test session.

5. **The login page has good UX:** clear branding ("Control Center"), accessible password input with label, disabled submit until password is entered, loading spinner text, styled error messages. The "This area is password-protected" subtitle sets user expectations.

6. **The `secure` flag on the session cookie is conditionally set** based on `NODE_ENV === "production"`. This is the correct pattern -- enforcing HTTPS-only cookies in production while allowing HTTP cookies in local development.

7. **Cross-reference with Audit I:** Defect H1 (env loading) overlaps with D16 from Audit I but adds the concrete finding that the `.env` file location is the active cause. Defect H7 (focus trap) overlaps with E5 from Audit I. All other findings in this audit are new.
