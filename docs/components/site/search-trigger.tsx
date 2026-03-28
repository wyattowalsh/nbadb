"use client";

import { useSearchContext } from "fumadocs-ui/contexts/search";
import type { ComponentProps } from "react";

/**
 * Thin client wrapper that opens the Fumadocs search dialog.
 * Used by server components that cannot call `useSearchContext` directly.
 */
export function SearchTrigger({
  children,
  ...props
}: Omit<ComponentProps<"button">, "onClick" | "type">) {
  const { setOpenSearch } = useSearchContext();

  return (
    <button type="button" onClick={() => setOpenSearch(true)} {...props}>
      {children}
    </button>
  );
}
