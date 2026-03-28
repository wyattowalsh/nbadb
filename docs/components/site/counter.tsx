"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function subscribeToReducedMotion(callback: () => void): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }

  const media = window.matchMedia(REDUCED_MOTION_QUERY);
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
}

function getReducedMotionSnapshot(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia(REDUCED_MOTION_QUERY).matches
  );
}

function easeOutExpo(t: number): number {
  return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
}

export function Counter({
  target,
  duration = 600,
  className,
}: {
  target: number;
  duration?: number;
  className?: string;
}) {
  const [value, setValue] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const hasAnimated = useRef(false);
  const prefersReducedMotion = useSyncExternalStore(
    subscribeToReducedMotion,
    getReducedMotionSnapshot,
    () => false,
  );

  useEffect(() => {
    const el = ref.current;
    hasAnimated.current = prefersReducedMotion;

    if (!el || prefersReducedMotion) {
      return;
    }

    hasAnimated.current = false;
    let rafId = 0;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !hasAnimated.current) {
          hasAnimated.current = true;
          const start = performance.now();

          function tick(now: number) {
            const elapsed = now - start;
            const progress = Math.min(elapsed / duration, 1);
            const eased = easeOutExpo(progress);
            setValue(Math.round(eased * target));

            if (progress < 1) {
              rafId = requestAnimationFrame(tick);
            }
          }

          rafId = requestAnimationFrame(tick);
        }
      },
      { threshold: 0.3 },
    );

    observer.observe(el);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(rafId);
    };
  }, [target, duration, prefersReducedMotion]);

  const displayValue = prefersReducedMotion ? target : value;
  const showShimmer = !prefersReducedMotion && displayValue === 0;

  return (
    <>
      <span
        ref={ref}
        className={
          showShimmer ? `nba-counter-shimmer ${className ?? ""}` : className
        }
        aria-hidden="true"
      >
        {showShimmer ? "\u00A0" : displayValue}
      </span>
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {displayValue === target ? String(target) : ""}
      </span>
    </>
  );
}
