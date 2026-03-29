import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AdminShell } from "@/components/admin/admin-shell";

export const metadata: Metadata = {
  title: {
    template: "%s | Control Center",
    default: "Control Center",
  },
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: ReactNode }) {
  const hasPassword = !!process.env.ADMIN_PASSWORD;

  return (
    <AdminShell>
      {!hasPassword && (
        <div
          role="alert"
          className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm font-medium text-amber-700 dark:text-amber-400"
        >
          Warning:{" "}
          <code className="rounded bg-amber-500/10 px-1 py-0.5 text-xs">
            ADMIN_PASSWORD
          </code>{" "}
          is not set. The admin panel is unprotected.
        </div>
      )}
      {children}
    </AdminShell>
  );
}
