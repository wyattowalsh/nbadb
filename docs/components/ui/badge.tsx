import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center justify-center gap-1 rounded-full border px-3 py-1.5 text-[0.63rem] font-semibold uppercase tracking-[0.26em] transition-colors duration-200",
  {
    variants: {
      variant: {
        signal:
          "border-primary/28 bg-primary/12 text-primary shadow-[inset_0_1px_0_color-mix(in_oklab,var(--primary)_16%,transparent)] dark:border-primary/22 dark:bg-primary/14",
        muted:
          "border-border/80 bg-background/72 text-muted-foreground shadow-[inset_0_1px_0_color-mix(in_oklab,var(--foreground)_6%,transparent)]",
        outline: "border-border/80 bg-transparent text-foreground",
        accent:
          "border-accent/30 bg-accent/18 text-accent-foreground shadow-[inset_0_1px_0_color-mix(in_oklab,var(--accent)_18%,transparent)] dark:border-accent/22 dark:bg-accent/16",
        board:
          "border-border/75 bg-card/78 text-foreground shadow-[0_8px_24px_-20px_color-mix(in_oklab,var(--foreground)_45%,transparent)]",
      },
    },
    defaultVariants: {
      variant: "signal",
    },
  },
);

type BadgeProps = HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof badgeVariants>;

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}
