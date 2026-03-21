import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full border text-sm font-semibold transition-[transform,background-color,border-color,color,box-shadow] duration-200 disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background active:translate-y-px [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "border-primary bg-primary text-primary-foreground shadow-[0_18px_38px_-22px_color-mix(in_oklab,var(--primary)_80%,transparent)] hover:bg-primary/92 hover:shadow-[0_20px_42px_-24px_color-mix(in_oklab,var(--primary)_78%,transparent)]",
        secondary:
          "border-border/80 bg-card/88 text-card-foreground shadow-[inset_0_1px_0_color-mix(in_oklab,var(--foreground)_6%,transparent)] hover:bg-accent/18 hover:text-foreground",
        outline:
          "border-border/85 bg-background/78 text-foreground shadow-[inset_0_1px_0_color-mix(in_oklab,var(--foreground)_6%,transparent)] hover:border-primary/24 hover:bg-accent/12 hover:text-foreground",
        ghost:
          "border-transparent bg-transparent text-foreground hover:bg-accent/12 hover:text-foreground",
        tint:
          "border-primary/18 bg-linear-to-r from-primary/12 via-primary/6 to-accent/10 text-foreground shadow-[inset_0_1px_0_color-mix(in_oklab,var(--foreground)_6%,transparent)] hover:border-primary/28 hover:from-primary/16 hover:to-accent/14",
      },
      size: {
        default: "h-11 px-5",
        sm: "h-9 px-4 text-xs tracking-[0.14em] uppercase",
        lg: "h-12 px-6 text-sm",
        icon: "size-10 rounded-full",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  },
);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot : "button";

  return (
    <Comp
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}
