---
title: Docs Admin Control Center
tags:
  - kb
  - topics
  - docs
  - admin
  - frontend
aliases:
  - Docs Control Center Shell
  - Admin Shell Contract
kind: concept
status: active
updated: 2026-04-15
source_count: 8
---

# Docs Admin Control Center

Use this note when you need the shell-level contract for the docs admin area: what the shared layout guarantees, how login hands off into the shell, how the mobile drawer behaves, what counts as canonical navigation, how sign-out is transported, and where the `/admin` overview splits server and client work.

## Layout policy
- `docs/app/(admin)/admin/layout.tsx` is the route-group wrapper for every authenticated admin page.
- The layout is always dynamic and always marked `robots: noindex, nofollow`.
- The layout delegates all persistent chrome to `AdminShell`, so page routes only provide page-local content.
- If `ADMIN_PASSWORD` is missing, the layout still renders but adds an amber warning banner explaining that the control center remains unavailable until the password is configured.
- `AdminShell` enforces the shell geometry:
  - desktop uses a persistent `lg` rail with `w-60`, right border, and sticky full-height column
  - mobile uses a top header plus off-canvas drawer
  - main content stays inside a centered `max-w-7xl` container with responsive horizontal padding

## Login UX
- `/admin/login` is the public entry page that collects only one credential: the admin password.
- The page auto-focuses the password field, disables submit while the field is empty or a request is in flight, and renders inline errors instead of redirecting to a separate error page.
- Submit sends JSON to `/api/admin/login`; success pushes to `/admin` and refreshes the router so server-rendered admin content re-evaluates immediately.
- The login copy makes the deployment dependency explicit: if sign-in is unavailable, check `ADMIN_PASSWORD`.
- The shell itself does not own login; it starts only after the route group has already admitted the request.

## Mobile drawer and focus trap
- `AdminShell` keeps drawer state in `sidebarOpen` and uses one shared shell for all mobile admin pages.
- Opening the drawer activates `useFocusTrap(true)` against the mobile `<aside>`.
- The trap behavior is local and explicit:
  - collect focusable links, buttons, inputs, and tabbable elements inside the drawer
  - move initial focus to the first focusable control when the drawer opens
  - wrap `Tab` from the last element back to the first
  - wrap `Shift+Tab` from the first element back to the last
- Closing paths are also explicit:
  - tap the backdrop overlay
  - press `Escape`
  - press the close button in the drawer header
- The drawer is labeled with `aria-label="Mobile navigation"`; the open and close buttons also carry aria labels.

## Nav contract
- `docs/components/admin/admin-nav.tsx` is the canonical nav definition.
- The allowed shell nav items are fixed by `navItems` in this order: `Overview`, `Content`, `Pipeline`, `Profiling`, `Health`.
- Active-state rules are part of the contract:
  - `Overview` is active only on exact `/admin`
  - the other items are active on exact match or any descendant route starting with their href
- Desktop and mobile shells both render the same `AdminNav`, so adding, removing, or reordering admin sections must happen in `admin-nav.tsx`, not separately in each shell variant.
- `Back to docs` and `Sign out` live in the shell footer and are not part of the canonical route list.

## Logout transport
- Sign-out is client-initiated from `AdminShell.handleLogout()`.
- The shell sends `POST /api/admin/logout`, then navigates to `/admin/login`, then refreshes the router.
- The API route returns `{ ok: true }` and clears the admin session cookie via `clearAdminSessionCookie(response)`.
- `docs/proxy.ts` explicitly treats `/api/admin/logout` as a public admin path, so logout remains callable without requiring an already-valid session.
- This means logout transport is intentionally split:
  - cookie invalidation is authoritative on the server route
  - UX completion happens in the client shell through push plus refresh

## Overview page role split
- `docs/app/(admin)/admin/page.tsx` is the server-owned coordinator for the control center home page.
- The server page does the privileged, aggregated work:
  - load content audit and pipeline summary in parallel
  - optionally load 7 day Umami stats only when analytics env vars are configured
  - derive the health summary and KPI values before HTML is returned
- `docs/app/(admin)/admin/overview-sparklines.tsx` is the client-owned analytics enhancer.
- The sparkline component fetches `/api/admin/umami` for 7 day and 30 day pageview series after hydration, shows skeletons while loading, and falls back to a configuration message if analytics is unavailable.
- The practical split is deliberate:
  - server page = authoritative operational summary for first paint
  - client sparklines = optional richer trend visualization that can fail soft without breaking the overview

## Related notes
- [[wiki/topics/docs-admin-surface|Docs Admin Surface]]
- [[wiki/topics/docs-telemetry-health|Docs Telemetry Health]]
- [[wiki/topics/docs-component-registry|Docs Component Registry]]
- [[wiki/topics/docs-app-stack|Docs App Stack]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| layout-level metadata, dynamic rendering, warning banner, `AdminShell` wrapper | `docs/app/(admin)/admin/layout.tsx` | route-group shell contract |
| shell geometry, mobile header, drawer state, focus trap, escape handling, footer actions, logout fetch transport | `docs/components/admin/admin-shell.tsx` | canonical admin shell behavior |
| canonical nav items and active-state matching rules | `docs/components/admin/admin-nav.tsx` | canonical navigation contract |
| login form shape, password-only UX, inline errors, disabled submit, router push/refresh on success | `docs/app/(admin)/admin/login/page.tsx` | login screen behavior |
| logout response payload and cookie clearing | `docs/app/api/admin/logout/route.ts` | authoritative server logout behavior |
| public admin path exceptions including logout and missing-password redirect behavior | `docs/proxy.ts` | auth boundary and public-path policy |
| overview page server-side aggregation, analytics env gate, KPI and health derivation | `docs/app/(admin)/admin/page.tsx` | overview server role |
| client sparkline fetches, skeleton state, analytics fallback card | `docs/app/(admin)/admin/overview-sparklines.tsx` | overview client role |
