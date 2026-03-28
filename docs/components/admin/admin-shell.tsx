"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Gauge, LogOut, Menu, X } from "lucide-react";
import { useState, useEffect, useRef, useCallback } from "react";
import { AdminNav } from "./admin-nav";
import { cn } from "@/lib/utils";

function useFocusTrap(active: boolean) {
  const containerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!active || !containerRef.current) return;
    const container = containerRef.current;
    const focusable = container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    if (focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    // Focus the first focusable element when the trap activates
    first.focus();

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key !== "Tab") return;
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    container.addEventListener("keydown", handleKeyDown);
    return () => container.removeEventListener("keydown", handleKeyDown);
  }, [active]);

  return containerRef;
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const mobileSidebarRef = useFocusTrap(sidebarOpen);

  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  // Close sidebar on Escape key
  useEffect(() => {
    if (!sidebarOpen) return;
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") closeSidebar();
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [sidebarOpen, closeSidebar]);

  async function handleLogout() {
    await fetch("/api/admin/logout", { method: "POST" });
    router.push("/admin/login");
    router.refresh();
  }

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 border-r border-sidebar-border bg-sidebar lg:block">
        <div className="sticky top-0 flex h-screen flex-col">
          <div className="flex items-center gap-2.5 border-b border-sidebar-border px-5 py-4">
            <Gauge className="size-5 text-primary" />
            <span className="text-sm font-bold uppercase tracking-[0.16em] text-foreground">
              Control Center
            </span>
          </div>
          <div className="flex-1 px-3 py-4">
            <AdminNav />
          </div>
          <div className="space-y-1 border-t border-sidebar-border px-3 py-3">
            <Link
              href="/docs"
              className="flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium text-sidebar-foreground/60 transition-colors hover:text-foreground"
            >
              <ArrowLeft className="size-3.5" />
              Back to docs
            </Link>
            <button
              onClick={handleLogout}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium text-sidebar-foreground/60 transition-colors hover:text-foreground"
            >
              <LogOut className="size-3.5" />
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Mobile sidebar */}
      <aside
        ref={mobileSidebarRef}
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-60 border-r border-sidebar-border bg-sidebar transition-transform duration-300 lg:hidden",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
        aria-label="Mobile navigation"
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-sidebar-border px-5 py-4">
            <div className="flex items-center gap-2.5">
              <Gauge className="size-5 text-primary" />
              <span className="text-sm font-bold uppercase tracking-[0.16em] text-foreground">
                Control Center
              </span>
            </div>
            <button
              onClick={closeSidebar}
              aria-label="Close sidebar"
              className="rounded-lg p-1 text-sidebar-foreground/60 hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          </div>
          <div className="flex-1 px-3 py-4">
            <AdminNav />
          </div>
          <div className="space-y-1 border-t border-sidebar-border px-3 py-3">
            <Link
              href="/docs"
              className="flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium text-sidebar-foreground/60 transition-colors hover:text-foreground"
            >
              <ArrowLeft className="size-3.5" />
              Back to docs
            </Link>
            <button
              onClick={handleLogout}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium text-sidebar-foreground/60 transition-colors hover:text-foreground"
            >
              <LogOut className="size-3.5" />
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Main content area */}
      <main className="flex-1">
        {/* Mobile header */}
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-border/70 bg-background/90 px-4 py-3 backdrop-blur-sm lg:hidden">
          <button
            onClick={() => setSidebarOpen(true)}
            className="rounded-lg p-1.5 text-muted-foreground hover:text-foreground"
          >
            <Menu className="size-5" />
          </button>
          <div className="flex items-center gap-2">
            <Gauge className="size-4 text-primary" />
            <span className="text-xs font-bold uppercase tracking-[0.16em] text-foreground">
              Control Center
            </span>
          </div>
        </header>
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          {children}
        </div>
      </main>
    </div>
  );
}
