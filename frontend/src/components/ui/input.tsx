import * as React from "react"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground h-10 w-full min-w-0 rounded-xl border bg-transparent px-4 py-2 text-base transition-all duration-200 outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        // Dark mode
        "dark:bg-white/[0.03] dark:border-[var(--border)] dark:text-[var(--text-main)]",
        "dark:placeholder:text-[var(--text-dim)]",
        "dark:hover:border-primary/30 dark:hover:bg-white/[0.05]",
        "dark:focus:border-primary/50 dark:focus:bg-white/[0.05]",
        "dark:focus:ring-2 dark:focus:ring-primary/20 dark:focus:shadow-[0_0_20px_rgba(0,209,255,0.15)]",
        // Light mode
        "border-slate-200 bg-white/80 text-slate-900",
        "placeholder:text-slate-400",
        "hover:border-primary/30 hover:bg-white",
        "focus:border-primary/50 focus:bg-white",
        "focus:ring-2 focus:ring-primary/10 focus:shadow-[0_0_15px_rgba(37,99,235,0.1)]",
        // Error state
        "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
        // Hide browser's native password reveal button (Edge/IE/Chrome)
        "[&::-ms-reveal]:hidden [&::-ms-clear]:hidden",
        "[&::-webkit-credentials-auto-fill-button]:hidden [&::-webkit-caps-lock-indicator]:hidden",
        className
      )}
      {...props}
    />
  )
}

// Search input (with search icon style)
function SearchInput({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <div className="relative">
      <svg
        className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-dim)] dark:text-[var(--text-dim)] text-slate-400"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
        />
      </svg>
      <Input
        className={cn(
          "pl-10",
          className
        )}
        {...props}
      />
    </div>
  )
}

// Rounded search input (modern style)
function RoundedSearchInput({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <div className="relative">
      <svg
        className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--text-dim)] dark:text-[var(--text-dim)] text-slate-400"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
        />
      </svg>
      <input
        type="text"
        data-slot="rounded-search-input"
        className={cn(
          "h-10 w-full min-w-0 rounded-full border bg-transparent pl-11 pr-4 py-2 text-base transition-all duration-200 outline-none disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
          // Dark mode
          "dark:bg-white/[0.03] dark:border-[var(--border)] dark:text-[var(--text-main)]",
          "dark:placeholder:text-[var(--text-dim)]",
          "dark:hover:border-primary/30 dark:hover:bg-white/[0.05]",
          "dark:focus:border-primary/50 dark:focus:bg-white/[0.05]",
          "dark:focus:ring-2 dark:focus:ring-primary/20 dark:focus:shadow-[0_0_20px_rgba(0,209,255,0.15)]",
          // Light mode
          "border-slate-200 bg-slate-50/50 text-slate-900",
          "placeholder:text-slate-400",
          "hover:border-primary/30 hover:bg-white",
          "focus:border-primary/50 focus:bg-white",
          "focus:ring-2 focus:ring-primary/10 focus:shadow-[0_0_15px_rgba(37,99,235,0.1)]",
          className
        )}
        {...props}
      />
    </div>
  )
}

export { Input, SearchInput, RoundedSearchInput }