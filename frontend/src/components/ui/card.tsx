import * as React from "react"

import { cn } from "@/lib/utils"

function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card"
      className={cn(
        "bg-card text-card-foreground flex flex-col gap-6 rounded-2xl border py-6 transition-all duration-200",
        // 暗色模式：玻璃态效果
        "dark:bg-white/[0.03] dark:border-[var(--border)] dark:backdrop-blur-sm",
        "dark:hover:bg-white/[0.05] dark:hover:border-primary/30",
        // 亮色模式：柔和阴影
        "bg-white shadow-[0_10px_30px_rgba(0,0,0,0.06)]",
        "hover:shadow-[0_15px_40px_rgba(0,0,0,0.08)]",
        className
      )}
      {...props}
    />
  )
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-2 px-6 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-6",
        className
      )}
      {...props}
    />
  )
}

function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-title"
      className={cn("leading-none font-semibold tracking-tight", className)}
      {...props}
    />
  )
}

function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
    />
  )
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "col-start-2 row-span-2 row-start-1 self-start justify-self-end",
        className
      )}
      {...props}
    />
  )
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("px-6", className)}
      {...props}
    />
  )
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn("flex items-center px-6 [.border-t]:pt-6", className)}
      {...props}
    />
  )
}

// 特殊卡片变体：玻璃卡片（更强的玻璃效果）
function GlassCard({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="glass-card"
      className={cn(
        "flex flex-col gap-6 rounded-2xl py-6 transition-all duration-200",
        // 暗色模式：强玻璃态
        "dark:bg-white/[0.02] dark:border dark:border-[var(--border)] dark:backdrop-blur-md",
        "dark:hover:bg-white/[0.04] dark:hover:border-primary/30",
        "dark:hover:shadow-[0_0_30px_rgba(0,209,255,0.1)]",
        // 亮色模式
        "bg-white border border-transparent shadow-lg",
        "hover:shadow-xl hover:border-primary/10",
        className
      )}
      {...props}
    />
  )
}

// 高亮卡片（用于选中状态）
function HighlightCard({ className, active, ...props }: React.ComponentProps<"div"> & { active?: boolean }) {
  return (
    <div
      data-slot="highlight-card"
      data-active={active}
      className={cn(
        "flex flex-col gap-4 rounded-2xl p-4 transition-all duration-200 cursor-pointer",
        // 暗色模式
        "dark:bg-white/[0.02] dark:border dark:border-transparent",
        "dark:hover:bg-white/[0.05] dark:hover:border-primary/20",
        // 亮色模式
        "bg-slate-50/50 border border-transparent",
        "hover:bg-slate-100/80 hover:border-primary/10",
        // 激活状态
        active && [
          "border-l-4 border-l-[var(--warm)]",
          "dark:bg-[var(--warm)]/5 dark:border-primary/20",
          "bg-[var(--warm)]/5",
        ],
        className
      )}
      {...props}
    />
  )
}

// 数据卡片（用于展示数据）
function DataCard({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="data-card"
      className={cn(
        "rounded-2xl p-5 transition-all duration-200",
        // 暗色模式
        "dark:bg-white/[0.03] dark:border dark:border-[var(--border)]",
        "dark:hover:border-primary/30 dark:hover:shadow-[0_0_20px_rgba(0,209,255,0.1)]",
        // 亮色模式
        "bg-gradient-to-br from-white to-slate-50/50 border border-slate-100",
        "hover:shadow-md hover:border-primary/10",
        className
      )}
      {...props}
    />
  )
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
  GlassCard,
  HighlightCard,
  DataCard,
}