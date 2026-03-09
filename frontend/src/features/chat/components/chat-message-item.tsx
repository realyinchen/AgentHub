import {
  CheckIcon,
  ChevronDown,
  CopyIcon,
  RefreshCcwIcon,
  WrenchIcon,
} from "lucide-react"
import { useEffect, useState } from "react"

import { Action, Actions } from "@/components/ai/actions"
import { Message, MessageContent } from "@/components/ai/message"
import { cn } from "@/lib/utils"
import type { LocalChatMessage, ToolCallInfo, StoredToolCallInfo } from "@/types"
import { MarkdownContent } from "@/components/ui/markdown-content"
import { useI18n } from "@/i18n"

type ChatMessageItemProps = {
  message: LocalChatMessage
  onRetry?: () => void
  retryDisabled?: boolean
  calledTools?: ToolCallInfo[]
  isAgentThinking?: boolean
  activeToolName?: string | null
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

/**
 * Parse stored tool info from message custom_data.
 * This is used to display tool calls from conversation history.
 */
function parseStoredToolInfo(message: LocalChatMessage): ToolCallInfo[] {
  const toolInfo = message.custom_data?.tool_info
  
  if (!Array.isArray(toolInfo) || toolInfo.length === 0) {
    return []
  }

  return toolInfo.map((info): ToolCallInfo => {
    const stored = info as StoredToolCallInfo
    return {
      name: stored.name || "unknown",
      id: stored.id || crypto.randomUUID(),
      args: stored.args || {},
      output: stored.output || undefined,
      status: "completed" as const, // Historical tool calls are always completed
    }
  })
}

export function ChatMessageItem({ 
  message, 
  onRetry, 
  retryDisabled = false, 
  calledTools = [], 
  isAgentThinking = false,
  activeToolName = null,
}: ChatMessageItemProps) {
  const { t } = useI18n()
  const isUser = message.type === "human"
  const isAI = message.type === "ai"
  const isTool = message.type === "tool"
  const isStreamingPlaceholder = isAI && message.is_streaming && !message.content.trim()
  const sources = parseSources(message)
  const reasoning = parseReasoning(message)
  const [copied, setCopied] = useState(false)
  const [showTools, setShowTools] = useState(false)

  // 不渲染工具类型的消息（工具调用结果）
  if (isTool) {
    return null
  }

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

  // Merge calledTools from streaming with stored tool_info from history
  // For streaming messages, use calledTools; for history messages, use stored tool_info
  const streamingTools = calledTools.length > 0 ? calledTools : parseStoredToolInfo(message)
  
  // Deduplicate tools by name
  const uniqueTools = streamingTools.reduce<ToolCallInfo[]>((acc, tool) => {
    if (!acc.some(t => t.name === tool.name)) {
      acc.push(tool)
    }
    return acc
  }, [])

  return (
    <article
      className={cn("flex w-full items-start gap-3", isUser && "justify-end")}
    >
      <Message
        from={isUser ? "user" : "assistant"}
        className={cn(
          "min-w-0 shrink-0",
          isUser
            ? "w-auto max-w-[72%] items-end"
            : isStreamingPlaceholder
              ? "w-auto max-w-[85%]"
              : "w-full max-w-[85%]",
        )}
      >
        <MessageContent
          className={cn(
            "max-w-full overflow-visible rounded-2xl px-4 py-3",
            isUser
              ? "w-fit mr-3  border-border/70 bg-muted/65 text-foreground group-[.is-user]:bg-muted/65 group-[.is-user]:text-foreground"
              : isStreamingPlaceholder
                ? "w-fit min-w-14 bg-muted/60 text-foreground"
                : "w-full bg-muted/60 text-foreground",
          )}
        >
          {sources.length > 0 ? (
            <details className="rounded-lg border border-border/80 bg-background/70 p-2 text-xs">
              <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground">
                <ChevronDown className="size-3" />
                {t("message.sources", { count: sources.length })}
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
                {t("message.reasoning")}
                {typeof reasoning.duration === "number" ? (
                  <span>({reasoning.duration}s)</span>
                ) : null}
              </summary>
              <div className="mt-2 whitespace-pre-wrap text-foreground">{reasoning.content}</div>
            </details>
          ) : null}

          {/* Thinking state for streaming placeholder */}
          {isStreamingPlaceholder && isAgentThinking ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="inline-flex gap-1">
                <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
                <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
                <span className="size-1.5 animate-bounce rounded-full bg-current" />
              </span>
              <span>
                {activeToolName
                  ? t("message.callingTool", { tool: activeToolName })
                  : t("message.thinking")}
              </span>
            </div>
          ) : null}

          {isAI ? (
            message.content ? (
              <MarkdownContent content={message.content} isStreaming={message.is_streaming} />
            ) : null
          ) : (
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {message.content}
            </p>
          )}
        </MessageContent>

        {/* Actions area: copy, retry, tools */}
        {isAI && !message.is_streaming ? (
          <div className={cn("flex flex-col", isUser ? "items-end" : "items-start")}>
            <Actions className={cn("pt-1", isUser ? "justify-end" : "justify-start")}>
              <Action
                onClick={() => {
                  void handleCopy()
                }}
                className="cursor-pointer"
                tooltip={copied ? t("common.copied") : t("common.copy")}
                label={copied ? t("message.copiedResponse") : t("message.copyResponse")}
              >
                {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
              </Action>
              <Action
                onClick={onRetry}
                tooltip={t("common.retry")}
                label={t("message.retryResponse")}
                className="cursor-pointer"
                disabled={!onRetry || retryDisabled}
              >
                <RefreshCcwIcon className="size-4" />
              </Action>
              {uniqueTools.length > 0 ? (
                <Action
                  onClick={() => setShowTools(!showTools)}
                  tooltip={showTools ? t("message.hideTools") : t("message.showTools")}
                  label={t("message.toolsUsedCount", { count: uniqueTools.length })}
                  className="cursor-pointer"
                >
                  <WrenchIcon className="size-4" />
                </Action>
              ) : null}
            </Actions>
            
            {/* Tool calls detail panel */}
            {uniqueTools.length > 0 && showTools ? (
              <div className="mt-2 w-full max-w-md rounded-lg border border-border/60 bg-background/50 p-3 text-xs">
                <div className="mb-2 font-medium text-muted-foreground">
                  {t("message.toolsUsedCount", { count: uniqueTools.length })}
                </div>
                <div className="space-y-2">
                  {uniqueTools.map((tool) => (
                    <div key={tool.id} className="rounded border border-border/40 bg-background/30 p-2">
                      <div className="font-medium text-foreground">{tool.name}</div>
                      {Object.keys(tool.args).length > 0 ? (
                        <div className="mt-1 text-muted-foreground">
                          <span className="font-medium">{t("message.toolInput")}:</span>
                          <pre className="mt-0.5 whitespace-pre-wrap break-all text-[11px]">
                            {JSON.stringify(tool.args, null, 2)}
                          </pre>
                        </div>
                      ) : null}
                      {tool.output ? (
                        <div className="mt-1 text-muted-foreground">
                          <span className="font-medium">{t("message.toolOutput")}:</span>
                          <pre className="mt-0.5 whitespace-pre-wrap break-all text-[11px] max-h-32 overflow-y-auto">
                            {tool.output}
                          </pre>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </Message>
    </article>
  )
}