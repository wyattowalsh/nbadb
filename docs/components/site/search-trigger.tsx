"use client";

import { useSearchContext } from "fumadocs-ui/contexts/search";
import { useCallback, useSyncExternalStore } from "react";
import type { ComponentProps } from "react";

const SEARCH_INPUT_SELECTORS = [
  "[cmdk-input]",
  "[data-search-input]",
  "dialog input[type='search']",
  "dialog input[type='text']",
  "[role='dialog'] input[type='search']",
  "[role='dialog'] input[type='text']",
] as const;
const SEARCH_PREFILL_RETRY_DELAYS_MS = [0, 80, 180] as const;

function findSearchInput(): HTMLInputElement | null {
  for (const selector of SEARCH_INPUT_SELECTORS) {
    const input = document.querySelector<HTMLInputElement>(selector);
    if (input) {
      return input;
    }
  }

  return null;
}

function fillSearchInput(input: HTMLInputElement, value: string): void {
  const nativeSetter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;

  nativeSetter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  input.focus();
  input.setSelectionRange(value.length, value.length);
}

function resolveSearchShortcutLabel(): string {
  if (typeof navigator === "undefined") {
    return "⌘K";
  }

  const platform =
    (
      navigator as Navigator & {
        userAgentData?: { platform?: string };
      }
    ).userAgentData?.platform ??
    navigator.platform ??
    "";
  return /mac|iphone|ipad/i.test(platform) ? "⌘K" : "Ctrl K";
}

export function SearchShortcutKey(
  props: Omit<ComponentProps<"kbd">, "children">,
) {
  const label = useSyncExternalStore(
    () => () => {},
    resolveSearchShortcutLabel,
    () => "⌘K",
  );

  return <kbd {...props}>{label}</kbd>;
}

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

    const tryPrefill = (attempt = 0) => {
      const input = findSearchInput();
      if (input) {
        fillSearchInput(input, query);
        return;
      }

      const nextDelay = SEARCH_PREFILL_RETRY_DELAYS_MS[attempt + 1];
      if (nextDelay === undefined) {
        console.warn(
          "[SearchTrigger] Unable to prefill the docs search dialog.",
        );
        return;
      }

      window.setTimeout(() => {
        requestAnimationFrame(() => {
          tryPrefill(attempt + 1);
        });
      }, nextDelay);
    };

    requestAnimationFrame(() => {
      tryPrefill();
    });
  }, [setOpenSearch, query]);

  return (
    <button type="button" onClick={handleClick} {...props}>
      {children}
    </button>
  );
}
