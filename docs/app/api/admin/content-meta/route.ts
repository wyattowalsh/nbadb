import { NextResponse } from "next/server";
import { getContentAudit } from "@/lib/admin/content-audit";

export const revalidate = 300;

export function GET() {
  const audit = getContentAudit();
  return NextResponse.json(audit);
}
