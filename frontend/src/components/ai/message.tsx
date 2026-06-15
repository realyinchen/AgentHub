import type { UIMessage } from "ai"
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

export type MessageProps = HTMLAttributes<HTMLDivElement> & {
  from: UIMessage["role"]
}

export const Message = ({ className, from, ...props }: MessageProps) => (
  <div
    className={cn(
      "group flex w-full max-w-[95%] flex-col gap-3",
      from === "user" ? "is-user ml-auto justify-end" : "is-assistant",
      "transition-all duration-200",
      className,
    )}
    {...props}
  />
)

export type MessageContentProps = HTMLAttributes<HTMLDivElement>

export const MessageContent = ({ children, className, ...props }: MessageContentProps) => (
  <div
    className={cn(
      "inline-flex w-fit max-w-full flex-col gap-2 text-sm",
      "group-[.is-user]:ml-auto group-[.is-user]:items-start group-[.is-user]:rounded-2xl group-[.is-user]:bg-[var(--warm)] group-[.is-user]:px-5 group-[.is-user]:py-3.5 group-[.is-user]:text-white group-[.is-user]:shadow-lg group-[.is-user]:shadow-[var(--warm)]/20",
      "group-[.is-assistant]:rounded-2xl group-[.is-assistant]:bg-[var(--bg-elevated)] group-[.is-assistant]:dark:bg-white/[0.03] group-[.is-assistant]:border group-[.is-assistant]:border-[var(--border)] group-[.is-assistant]:px-5 group-[.is-assistant]:py-4 group-[.is-assistant]:backdrop-blur-sm",
      "group-[.is-assistant]:text-[var(--text-main)] group-[.is-user]:text-white",
      "transition-all duration-200",
      className,
    )}
    {...props}
  >
    {children}
  </div>
)