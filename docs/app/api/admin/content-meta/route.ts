import { NextResponse } from "next/server";
import { getContentAudit } from "@/lib/admin/content-audit";

export const revalidate = 300;

export async function GET() {
  const audit = await getContentAudit();
  return NextResponse.json(audit);
}
