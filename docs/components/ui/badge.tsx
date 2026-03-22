import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center justify-center gap-1 border px-2 py-0.5 text-[0.65rem] font-semibold uppercase tracking-[0.2em] transition-colors duration-150",
  {
    variants: {
      variant: {
        default: "border-border bg-transparent text-muted-foreground",
        primary: "border-primary/30 bg-transparent text-primary",
        accent: "border-accent/30 bg-transparent text-accent",
        stat: "border-primary/40 bg-primary/10 text-primary",
        outline: "border-border bg-transparent text-foreground",
        muted: "border-border bg-muted text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
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
