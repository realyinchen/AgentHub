import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-full px-3 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1.5 [&>svg]:pointer-events-none transition-all duration-200 overflow-hidden",
  {
    variants: {
      variant: {
        default: "bg-[var(--primary)] text-white dark:bg-[var(--primary)]/20 dark:text-[var(--primary)] dark:border dark:border-[var(--primary)]/30 hover:scale-105",
        secondary:
          "bg-[var(--bg-elevated)] text-[var(--text-main)] dark:bg-white/10 dark:text-[var(--text-main)] border border-[var(--border)] hover:bg-[var(--bg-elevated)]/80 dark:hover:bg-white/15",
        destructive:
          "bg-red-500/90 text-white dark:bg-red-500/20 dark:text-red-400 dark:border dark:border-red-500/30 hover:bg-red-600 dark:hover:bg-red-500/30",
        outline:
          "border border-[var(--border)] text-[var(--text-main)] bg-transparent hover:bg-[var(--bg-elevated)] dark:hover:bg-white/5",
        ghost: "text-[var(--text-dim)] hover:bg-[var(--bg-elevated)] dark:hover:bg-white/5 hover:text-[var(--text-main)]",
        link: "text-[var(--primary)] underline-offset-4 hover:underline",
        warm: "bg-[var(--warm)] text-white dark:bg-[var(--warm)]/20 dark:text-[var(--warm)] dark:border dark:border-[var(--warm)]/30 hover:scale-105 shadow-sm hover:shadow-[0_0_12px_rgba(255,159,69,0.3)]",
        success: "bg-emerald-500/90 text-white dark:bg-emerald-500/20 dark:text-emerald-400 dark:border dark:border-emerald-500/30",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
