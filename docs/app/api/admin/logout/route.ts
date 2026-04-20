import { NextResponse } from "next/server";
import { clearAdminSessionCookie } from "@/lib/admin/session";

export function POST() {
  const response = NextResponse.json({ ok: true });
  clearAdminSessionCookie(response);
  return response;
}
