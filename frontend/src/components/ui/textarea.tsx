import * as React from "react"

import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        // Base styles with modern design
        "flex field-sizing-content min-h-16 w-full rounded-2xl px-4 py-3 text-[15px] leading-relaxed",
        // Border and background
        "border border-[var(--border)] bg-[var(--bg-elevated)] dark:bg-[rgba(255,255,255,0.03)]",
        // Placeholder
        "placeholder:text-[var(--text-dim)]",
        // Transitions
        "transition-all duration-200 ease-out outline-none",
        // Focus state with warm glow
        "focus:border-[var(--warm)] focus:ring-2 focus:ring-[var(--warm)]/20",
        "dark:focus:shadow-[0_0_0_3px_rgba(255,159,69,0.15)]",
        "light:focus:shadow-[0_0_0_3px_rgba(255,159,69,0.1)]",
        // Hover state
        "hover:border-[var(--primary)]/30 dark:hover:border-[var(--primary)]/40",
        // Disabled state
        "disabled:cursor-not-allowed disabled:opacity-50",
        // Text color
        "text-[var(--text-main)]",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
