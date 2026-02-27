import {
  Bot,
  CheckIcon,
  ChevronDown,
  CopyIcon,
  RefreshCcwIcon,
  User,
} from "lucide-react"
import { useEffect, useState } from "react"

import { Action, Actions } from "@/components/ai/actions"
import { Message, MessageContent } from "@/components/ai/message"
import { cn } from "@/lib/utils"
import type { LocalChatMessage } from "@/types"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { MarkdownContent } from "@/components/ui/markdown-content"

type ChatMessageItemProps = {
  message: LocalChatMessage
  onRetry?: () => void
  retryDisabled?: boolean
}

type SourceLink = {
  href: string
  title: string
}

function parseSources(message: LocalChatMessage): SourceLink[] {
  const candidates = [
    message.custom_data?.sources,
    message.response_metadata?.sources,
  ]

  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) {
      continue
    }

    const normalized = candidate
      .map((item) => {
        if (!item || typeof item !== "object") {
          return null
        }

        const record = item as Record<string, unknown>
        const href =
          typeof record.href === "string"
            ? record.href
            : typeof record.url === "string"
              ? record.url
              : null

        if (!href) {
          return null
        }

        return {
          href,
          title:
            typeof record.title === "string"
              ? record.title
              : typeof record.name === "string"
                ? record.name
                : href,
        }
      })
      .filter((item): item is SourceLink => Boolean(item))

    if (normalized.length > 0) {
      return normalized
    }
  }

  return []
}

function parseReasoning(message: LocalChatMessage): { content: string; duration?: number } | null {
  const candidates = [
    message.custom_data?.reasoning,
    message.response_metadata?.reasoning,
    message.response_metadata?.thinking,
  ]

  for (const candidate of candidates) {
    if (!candidate) {
      continue
    }

    if (typeof candidate === "string" && candidate.trim()) {
      return { content: candidate.trim() }
    }

    if (candidate && typeof candidate === "object") {
      const record = candidate as Record<string, unknown>
      const content =
        typeof record.content === "string"
          ? record.content
          : typeof record.text === "string"
            ? record.text
            : null

      if (!content || !content.trim()) {
        continue
      }

      return {
        content: content.trim(),
        duration: typeof record.duration === "number" ? record.duration : undefined,
      }
    }
  }

  return null
}

export function ChatMessageItem({ message, onRetry, retryDisabled = false }: ChatMessageItemProps) {
  const isUser = message.type === "human"
  const isAI = message.type === "ai"
  const sources = parseSources(message)
  const reasoning = parseReasoning(message)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) {
      return
    }

    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  const handleCopy = async () => {
    if (!message.content.trim()) {
      return
    }

    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
    } catch {
      // Ignore clipboard failures in unsupported environments.
    }
  }

  return (
    <article
      className={cn("flex w-full items-start gap-3", isUser && "justify-end")}
    >
      {/* {!isUser ? (
        <Avatar className="mt-1 size-8 border border-border">
          <AvatarFallback className="bg-muted text-muted-foreground">
            <Bot className="size-4" />
          </AvatarFallback>
        </Avatar>
      ) : null} */}

      <Message
        from={isUser ? "user" : "assistant"}
        className={cn(
          "min-w-0 shrink-0",
          isUser ? "w-auto max-w-[72%] items-end" : "w-full max-w-[85%]",
        )}
      >
        <MessageContent
          className={cn(
            "max-w-full space-y-3 overflow-visible rounded-2xl px-4 py-3",
            isUser
              ? "w-fit mr-3  border-border/70 bg-muted/65 text-foreground group-[.is-user]:bg-muted/65 group-[.is-user]:text-foreground"
              : "w-full bg-muted/60 text-foreground",
          )}
        >
          {sources.length > 0 ? (
            <details className="rounded-lg border border-border/80 bg-background/70 p-2 text-xs">
              <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground">
                <ChevronDown className="size-3" />
                Sources ({sources.length})
              </summary>
              <div className="mt-2 space-y-1">
                {sources.map((source) => (
                  <a
                    key={source.href}
                    href={source.href}
                    target="_blank"
                    rel="noreferrer"
                    className="block truncate text-primary hover:underline"
                  >
                    {source.title}
                  </a>
                ))}
              </div>
            </details>
          ) : null}

          {reasoning ? (
            <details className="rounded-lg border border-border/80 bg-background/70 p-2 text-xs">
              <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground">
                <ChevronDown className="size-3" />
                Reasoning
                {typeof reasoning.duration === "number" ? (
                  <span>({reasoning.duration}s)</span>
                ) : null}
              </summary>
              <div className="mt-2 whitespace-pre-wrap text-foreground">{reasoning.content}</div>
            </details>
          ) : null}

          {isAI ? (
            message.content ? (
              <MarkdownContent content={message.content} />
            ) : message.is_streaming ? (
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <span className="inline-flex gap-1">
                  <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
                  <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
                  <span className="size-1.5 animate-bounce rounded-full bg-current" />
                </span>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No visible output.</p>
            )
          ) : (
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {message.content || "No visible output."}
            </p>
          )}

          {message.tool_calls.length > 0 ? (
            <div className="space-y-2">
              {message.tool_calls.map((call) => (
                <div key={call.id} className="space-y-2 rounded-xl border bg-background/80 p-3">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">Tool</Badge>
                    <span className="text-xs font-medium">{call.name}</span>
                  </div>
                  <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs text-foreground">
                    {JSON.stringify(call.args, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          ) : null}

          {message.type === "tool" ? (
            <Badge variant="secondary" className="font-normal">
              tool call id: {message.tool_call_id || "unknown"}
            </Badge>
          ) : null}
        </MessageContent>

        {isAI && !message.is_streaming ? (
          <Actions className={cn("pt-1", isUser ? "justify-end" : "justify-start")}>
            <Action
              onClick={() => {
                void handleCopy()
              }}
              className="cursor-pointer"
              tooltip={copied ? "Copied" : "Copy"}
              label={copied ? "Copied response" : "Copy response"}
            >
              {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
            </Action>
            <Action
              onClick={onRetry}
              tooltip="Retry"
              label="Retry response"
              className="cursor-pointer"
              disabled={!onRetry || retryDisabled}
            >
              <RefreshCcwIcon className="size-4" />
            </Action>
          </Actions>
        ) : null}
      </Message>

      {/* {isUser ? (
        <Avatar className="mt-1 size-8 border border-border">
          <AvatarFallback className="bg-primary/10 text-primary">
            <User className="size-4" />
          </AvatarFallback>
        </Avatar>
      ) : null} */}
    </article>
  )
}
