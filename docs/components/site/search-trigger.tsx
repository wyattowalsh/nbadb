"use client";

import { useSearchContext } from "fumadocs-ui/contexts/search";
import { useCallback } from "react";
import type { ComponentProps } from "react";

/**
 * Thin client wrapper that opens the Fumadocs search dialog.
 * Used by server components that cannot call `useSearchContext` directly.
 *
 * When `query` is provided the search input is pre-filled after the dialog
 * opens so the user lands directly on matching results.
 */
export function SearchTrigger({
  children,
  query,
  ...props
}: Omit<ComponentProps<"button">, "onClick" | "type"> & {
  /** Optional query string to pre-fill in the search input */
  query?: string;
}) {
  const { setOpenSearch } = useSearchContext();

  const handleClick = useCallback(() => {
    setOpenSearch(true);

    if (!query) return;

    // After the dialog mounts, find the search input and fill it.
    // Use a short RAF + timeout chain so the dialog has rendered.
    requestAnimationFrame(() => {
      setTimeout(() => {
        const input = document.querySelector<HTMLInputElement>(
          "[cmdk-input], [data-search-input], dialog input[type='text'], dialog input[type='search'], [role='dialog'] input",
        );
        if (!input) return;

        // Use the native setter so React picks up the change event.
        const nativeSetter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )?.set;
        nativeSetter?.call(input, query);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }, 80);
    });
  }, [setOpenSearch, query]);

  return (
    <button type="button" onClick={handleClick} {...props}>
      {children}
    </button>
  );
}
