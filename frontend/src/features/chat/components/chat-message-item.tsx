import {
  BrainIcon,
  CheckIcon,
  ChevronDown,
  ChevronDownIcon,
  ChevronRightIcon,
  CopyIcon,
  PencilIcon,
  QuoteIcon,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Action, Actions } from "@/components/ai/actions"
import { Message, MessageContent } from "@/components/ai/message"
import { cn } from "@/lib/utils"
import type { LocalChatMessage, ToolCallInfo, StoredToolCallInfo, AgentProcessSession, MessageStep, ToolCallEvent } from "@/types"
import { MarkdownContent } from "@/components/ui/markdown-content"
import { Separator } from "@/components/ui/separator"
import { useI18n } from "@/i18n"

type ChatMessageItemProps = {
  message: LocalChatMessage
  messageIndex: number // Index in messages array for edit functionality
  calledTools?: ToolCallInfo[]
  isAgentThinking?: boolean
  thinkingContent?: string // Accumulated thinking content (streaming)
  isProcessing?: boolean // Processing, no content received yet
  isStreaming?: boolean // Whether the current message is streaming
  processSession?: AgentProcessSession | null // Process session for inline display during streaming
  messageSequence?: MessageStep[] // Message sequence for historical display
  onEditMessage?: (newContent: string, messageIndex: number) => void // Callback when user edits their message, with index
  editDisabled?: boolean // Whether edit is disabled
  onQuote?: () => void // Callback when user wants to quote this message
  quoteDisabled?: boolean // Whether quote is disabled
  onJumpToMessage?: (localId: string) => void // Jump to quoted message
  onToggleSidebarProcess?: () => void // Toggle sidebar process panel visibility
}

type SourceLink = {
  href: string
  title: string
}

/**
 * Parse quoted content from message.
 * Format: "> quoted content\n\nnew message"
 * Returns { quotedContent, newContent } or null if not a quoted message.
 */
function parseQuotedContent(content: string): { quotedContent: string; newContent: string } | null {
  // Check if message starts with "> "
  if (!content.startsWith("> ")) {
    return null
  }

  // Find the separator "\n\n" after the quoted content
  const separatorIndex = content.indexOf("\n\n")
  if (separatorIndex === -1) {
    return null
  }

  // Extract quoted content (remove "> " prefix)
  const quotedContent = content.slice(2, separatorIndex)
  // Extract new content (after "\n\n")
  const newContent = content.slice(separatorIndex + 2)

  if (!quotedContent.trim() || !newContent.trim()) {
    return null
  }

  return { quotedContent, newContent }
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

/**
 * Parse thinking content from message.
 * Checks multiple sources for compatibility.
 */
function parseThinkingContent(message: LocalChatMessage): string | null {
  // 1. Check custom_data.thinking (saved from backend)
  const thinkingFromCustomData = message.custom_data?.thinking
  if (typeof thinkingFromCustomData === "string" && thinkingFromCustomData.trim()) {
    return thinkingFromCustomData.trim()
  }

  // 2. Check response_metadata.thinking
  const thinkingFromMetadata = message.response_metadata?.thinking
  if (typeof thinkingFromMetadata === "string" && thinkingFromMetadata.trim()) {
    return thinkingFromMetadata.trim()
  }

  // 3. Check reasoning_content
  const reasoningContent = message.reasoning_content
  if (typeof reasoningContent === "string" && reasoningContent.trim()) {
    return reasoningContent.trim()
  }

  // 4. Check custom_data.reasoning
  const reasoningFromCustomData = message.custom_data?.reasoning
  if (typeof reasoningFromCustomData === "string" && reasoningFromCustomData.trim()) {
    return reasoningFromCustomData.trim()
  }

  return null
}

/**
 * Parse stored tool info from message custom_data.
 * This is used to display tool calls from conversation history.
 */
function parseStoredToolInfo(message: LocalChatMessage): ToolCallInfo[] {
  try {
    const toolInfo = message.custom_data?.tool_info

    if (!Array.isArray(toolInfo) || toolInfo.length === 0) {
      return []
    }

    // Check if all items have order field - if so, sort by order
    // Otherwise, keep original array order (which should be correct from backend)
    const hasOrderField = toolInfo.every(
      (item) => {
        const stored = item as StoredToolCallInfo
        return stored && typeof stored.order === "number"
      }
    )

    const sortedInfo = hasOrderField
      ? [...toolInfo].sort((a, b) => {
        const orderA = (a as StoredToolCallInfo).order as number
        const orderB = (b as StoredToolCallInfo).order as number
        return orderA - orderB
      })
      : toolInfo

    return sortedInfo.map((info, index): ToolCallInfo => {
      const stored = info as StoredToolCallInfo
      return {
        name: (stored?.name as string) || "unknown",
        id: (stored?.id as string) || `tool-${index}-${Date.now()}`,
        args: (stored?.args as Record<string, unknown>) || {},
        output: (stored?.output as string | undefined) || undefined,
        status: "completed" as const,
      }
    })
  } catch {
    // Ignore parsing errors for malformed tool info
    return []
  }
}

/**
 * Group consecutive tool calls with the same name.
 * Returns an array of grouped tool calls with count.
 */
type GroupedToolCall = {
  name: string
  count: number
  tools: ToolCallInfo[]
}

function groupConsecutiveToolCalls(tools: ToolCallInfo[]): GroupedToolCall[] {
  if (tools.length === 0) {
    return []
  }

  const groups: GroupedToolCall[] = []
  let currentGroup: GroupedToolCall = {
    name: tools[0].name,
    count: 1,
    tools: [tools[0]],
  }

  for (let i = 1; i < tools.length; i++) {
    const tool = tools[i]
    if (tool.name === currentGroup.name) {
      // Same tool as previous - add to current group
      currentGroup.count++
      currentGroup.tools.push(tool)
    } else {
      // Different tool - push current group and start new one
      groups.push(currentGroup)
      currentGroup = {
        name: tool.name,
        count: 1,
        tools: [tool],
      }
    }
  }

  // Don't forget to push the last group
  groups.push(currentGroup)

  return groups
}

// ==================== Inline Process Steps Types ====================

type InlineTimelineStepType = "ai_thinking" | "tool" | "ai_final"

type InlineTimelineStep = {
  id: string
  stepNumber: number
  type: InlineTimelineStepType
  title: string
  content: string
  args?: string
  result?: string
  thinking?: string
  status: "running" | "done"
  timestamp: number
}

// ==================== Inline Process Steps Component ====================

function InlineProcessSteps({
  session,
  messageSequence,
  isStreaming,
}: {
  session?: AgentProcessSession | null
  messageSequence?: MessageStep[]
  isStreaming: boolean
}) {
  const { t } = useI18n()
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())

  // Convert streaming session to timeline steps
  const getTimelineStepsFromSession = (): InlineTimelineStep[] => {
    if (!session || !session.steps || session.steps.length === 0) {
      return []
    }

    const steps: InlineTimelineStep[] = []

    session.steps.forEach((step) => {
      // Skip human messages
      if (step.type === "human") {
        return
      }
      
      if (step.type === "thinking") {
        steps.push({
          id: step.id,
          stepNumber: steps.length,
          type: "ai_thinking",
          title: t("process.thinking"),
          content: "",
          thinking: step.content as string,
          status: step.status === "done" ? "done" : "running",
          timestamp: step.timestamp,
        })
      } else if (step.type === "tool_call") {
        const toolCall = step.content as ToolCallEvent
        steps.push({
          id: step.id,
          stepNumber: steps.length,
          type: "tool",
          title: toolCall.name,
          content: "",
          result: step.result || "",
          status: step.status === "done" ? "done" : "running",
          timestamp: step.timestamp,
        })
      } else if (step.type === "ai_response") {
        const thinkingContent = step.thinking || ""
        const hasThinking = thinkingContent.trim().length > 0
        const contentStr = (step.content as string) || ""
        const hasContent = contentStr.trim().length > 0
        
        steps.push({
          id: step.id,
          stepNumber: steps.length,
          type: "ai_final",
          title: t("process.modelResponse"),
          content: hasContent ? contentStr : "",
          thinking: hasThinking ? thinkingContent : undefined,
          status: "done",
          timestamp: step.timestamp,
        })
      }
    })

    return steps
  }

  // Convert message sequence to timeline steps
  const getTimelineStepsFromSequence = (): InlineTimelineStep[] => {
    if (!messageSequence || messageSequence.length === 0) {
      return []
    }

    const steps: InlineTimelineStep[] = []

    messageSequence.forEach((msg) => {
      if (msg.message_type === "tool") {
        const argsStr = msg.tool_args && Object.keys(msg.tool_args).length > 0
          ? JSON.stringify(msg.tool_args, null, 2)
          : undefined
        
        steps.push({
          id: `step-${msg.step_number}-tool`,
          stepNumber: msg.step_number,
          type: "tool",
          title: msg.tool_name || t("process.toolCall"),
          content: "",
          args: argsStr,
          result: msg.tool_output || "",
          status: "done",
          timestamp: Date.now(),
        })
      } else if (msg.message_type === "ai") {
        const thinkingContent = msg.thinking || ""
        const hasThinking = thinkingContent.trim().length > 0
        const contentStr = msg.content || ""
        const hasContent = contentStr.trim().length > 0
        
        steps.push({
          id: `step-${msg.step_number}-ai-final`,
          stepNumber: msg.step_number,
          type: "ai_final",
          title: t("process.modelResponse"),
          content: hasContent ? contentStr : "",
          thinking: hasThinking ? thinkingContent : undefined,
          status: "done",
          timestamp: Date.now(),
        })
      }
    })

    return steps
  }

  // Determine which steps to show
  const timelineSteps = isStreaming && session?.isActive
    ? getTimelineStepsFromSession()
    : getTimelineStepsFromSequence()

  // Auto-expand last step when new steps arrive
  useEffect(() => {
    if (timelineSteps.length > 0) {
      const lastStepId = timelineSteps[timelineSteps.length - 1].id
      setExpandedSteps(prev => {
        const next = new Set(prev)
        next.add(lastStepId)
        return next
      })
    }
  }, [timelineSteps.length])

  const toggleStep = (stepId: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev)
      if (next.has(stepId)) {
        next.delete(stepId)
      } else {
        next.add(stepId)
      }
      return next
    })
  }

  if (timelineSteps.length === 0) {
    return null
  }

  // Icon mapping
  const getIcon = (type: InlineTimelineStepType) => {
    if (type === "ai_thinking" || type === "ai_final") {
      return "🧠"
    }
    return "🔧"
  }

  return (
    <div className="rounded-lg border border-border/60 bg-background/50 p-2 text-xs mb-2">
      <div className="space-y-0">
        {timelineSteps.map((step, index) => {
          const isExpanded = expandedSteps.has(step.id)
          const isLast = index === timelineSteps.length - 1
          const isRunning = step.status === "running"

          return (
            <div key={step.id} className="relative">
              {/* Timeline vertical line */}
              {!isLast && (
                <div className="absolute left-[11px] top-5 bottom-0 w-0.5 bg-gray-200 dark:bg-gray-700" />
              )}

              {/* Step row */}
              <div className="flex items-start gap-2">
                {/* Dot/Circle */}
                <div
                  className={cn(
                    "flex-shrink-0 size-5 rounded-full flex items-center justify-center text-[10px] z-10",
                    isRunning
                      ? "bg-blue-100 dark:bg-blue-900/30 animate-pulse"
                      : "bg-green-100 dark:bg-green-900/30"
                  )}
                >
                  {isRunning ? (
                    <span className="size-1.5 rounded-full bg-blue-500 animate-pulse" />
                  ) : (
                    <span className="text-green-600 dark:text-green-400 text-[8px]">✔</span>
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0 pb-2">
                  {/* Header - clickable */}
                  <button
                    type="button"
                    onClick={() => toggleStep(step.id)}
                    className="w-full text-left flex items-center gap-1.5 group"
                  >
                    {/* Expand/Collapse icon */}
                    {isExpanded ? (
                      <ChevronDownIcon className="size-3 text-gray-400 flex-shrink-0" />
                    ) : (
                      <ChevronRightIcon className="size-3 text-gray-400 flex-shrink-0" />
                    )}

                    {/* Icon */}
                    <span className="text-xs">{getIcon(step.type)}</span>

                    {/* Title */}
                    <span className="text-[11px] font-medium text-gray-700 dark:text-gray-300 truncate flex-1">
                      {step.title}
                    </span>
                  </button>

                  {/* Expandable content */}
                  {isExpanded && (
                    <div className="mt-1.5 ml-5 space-y-2">
                      {/* AI Thinking step - show reasoning and content in separate blocks */}
                      {step.type === "ai_final" && (step.thinking || step.content) && (
                        <>
                          {/* Reasoning block */}
                          {step.thinking && (
                            <div>
                              <div className="text-[9px] text-gray-500 dark:text-gray-400 mb-0.5 font-medium">
                                {t("process.reasoning") || "Reasoning"}
                              </div>
                              <div className="rounded-md bg-amber-50 dark:bg-amber-900/20 p-2 text-[11px] text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                                {step.thinking}
                              </div>
                            </div>
                          )}
                          
                          {/* Content block */}
                          {step.content && (
                            <div>
                              <div className="text-[9px] text-gray-500 dark:text-gray-400 mb-0.5 font-medium">
                                {t("process.content") || "Content"}
                              </div>
                              <div className="rounded-md bg-gray-100 dark:bg-gray-800/50 p-2 text-[11px] text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                                {step.content}
                              </div>
                            </div>
                          )}
                        </>
                      )}

                      {/* AI Thinking step during streaming */}
                      {step.type === "ai_thinking" && step.thinking && (
                        <div className="rounded-md bg-amber-50 dark:bg-amber-900/20 p-2 text-[11px] text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                          {step.thinking}
                        </div>
                      )}

                      {/* Args (for tool result steps) */}
                      {step.args && (
                        <div>
                          <div className="text-[9px] text-gray-500 dark:text-gray-400 mb-0.5">
                            {t("process.arguments")}
                          </div>
                          <div className="rounded-md bg-gray-100 dark:bg-gray-800/50 p-2 text-[11px] text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-32 overflow-y-auto font-mono">
                            {step.args}
                          </div>
                        </div>
                      )}

                      {/* Result (for tool result steps) - show directly without "Result" label */}
                      {step.result && (
                        <div className="rounded-md bg-gray-100 dark:bg-gray-800/50 p-2 text-[11px] text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                          {step.result}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function ChatMessageItem({
  message,
  messageIndex,
  calledTools = [],
  thinkingContent = "",
  isProcessing = false,
  isStreaming = false,
  processSession,
  messageSequence,
  onEditMessage,
  editDisabled = false,
  onQuote,
  quoteDisabled = false,
  onJumpToMessage,
  onToggleSidebarProcess,
}: ChatMessageItemProps) {
  const messageRef = useRef<HTMLDivElement>(null)
  const { t } = useI18n()
  const isUser = message.type === "human"
  const isAI = message.type === "ai"
  const isTool = message.type === "tool"
  const sources = parseSources(message)
  const [copied, setCopied] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  // For quoted messages, edit only the user_content; otherwise edit the full content
  const [editContent, setEditContent] = useState(
    (isUser && message.custom_data?.user_content as string | undefined) || message.content
  )
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [isHovered, setIsHovered] = useState(false)

  // Parse thinking content from message (for history) or use streaming content
  const historicalThinking = parseThinkingContent(message)
  const displayThinkingContent = thinkingContent || historicalThinking || ""
  const hasThinkingContent = Boolean(displayThinkingContent)

  // Merge calledTools from streaming with stored tool_info from history
  // For streaming messages, use calledTools; for history messages, use stored tool_info
  const allTools = calledTools.length > 0 ? calledTools : parseStoredToolInfo(message)
  const hasToolCalls = allTools.length > 0

  // Don't render tool type messages (tool call results)
  if (isTool) {
    return null
  }

  // For AI messages, don't render if there's no content, thinking content, or tool calls
  // This avoids empty bubbles
  // But during streaming, show processing state even without content
  if (isAI && !isStreaming && !message.content.trim() && !hasThinkingContent && !hasToolCalls) {
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

  // Determine what to show in the action bar
  // Show a single "agent process" button if there's thinking content or tool calls
  const showAgentProcessButton = hasThinkingContent || hasToolCalls

  // Get quoted message ID and user content from custom_data
  const quotedMessageId = message.custom_data?.quoted_message_id as string | undefined
  const userContent = message.custom_data?.user_content as string | undefined

  // Check if this is a quoted message (has quoted_message_id and user_content)
  const isQuotedMessage = isUser && quotedMessageId && userContent

  // Parse quoted content from message content for display
  // Format: "> quoted content\n\nuser message"
  const quotedParts = isQuotedMessage ? parseQuotedContent(message.content) : null

  // Truncate quoted content to 100 chars with underscore
  const getTruncatedQuote = (content: string) => {
    if (content.length > 100) {
      return `${content.slice(0, 100)}_`
    }
    return content
  }

  return (
    <article
      id={`message-${message.local_id}`}
      ref={messageRef}
      className={cn("flex w-full items-start gap-3", isUser && "justify-end")}
    >
      <Message
        from={isUser ? "user" : "assistant"}
        className={cn(
          "min-w-0 shrink-0",
          isUser
            ? "w-auto max-w-[72%] items-end"
            : "w-full max-w-[85%]",
        )}
        onMouseEnter={() => isUser && setIsHovered(true)}
        onMouseLeave={() => isUser && setIsHovered(false)}
      >
        <MessageContent
          className={cn(
            "max-w-full overflow-visible rounded-3xl px-5 py-3.5 text-[15px] leading-relaxed",
            isUser
              ? "w-fit mr-3 bg-user-bubble text-user-bubble-foreground"
              : "w-full bg-ai-bubble text-foreground border border-border/50",
          )}
        >
          {/* Sources */}
          {sources.length > 0 ? (
            <details className="rounded-lg border border-border/80 bg-background/70 p-2 text-xs mb-2">
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

          {/* Inline Process Steps - show during streaming when there's process session data */}
          {isAI && isStreaming && processSession?.isActive && (
            <InlineProcessSteps
              session={processSession}
              messageSequence={messageSequence}
              isStreaming={isStreaming}
            />
          )}

          {/* Processing state - show loading animation before any content arrives */}
          {isAI && isStreaming && isProcessing && !message.content.trim() && !displayThinkingContent && allTools.length === 0 && !processSession?.isActive ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="inline-flex gap-1">
                <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
                <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
                <span className="size-1.5 animate-bounce rounded-full bg-current" />
              </span>
              <span>{t("message.processing")}</span>
            </div>
          ) : null}

          {/* Thinking process - only show when there is actual thinking content and no process session */}
          {isAI && hasThinkingContent && isStreaming && !message.content.trim() && !processSession?.isActive ? (
            <details className="rounded-lg border border-border/60 bg-background/50 p-2 text-xs mb-2" open>
              <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground">
                <BrainIcon className="size-3" />
                {t("message.thinking")}
              </summary>
              <div className="mt-2 whitespace-pre-wrap text-muted-foreground max-h-40 overflow-y-auto">
                {displayThinkingContent}
              </div>
            </details>
          ) : null}

          {/* Tool calls during streaming - only show completed tools (with output) and no process session */}
          {isAI && allTools.some(t => t.status === "completed") && isStreaming && !message.content.trim() && !processSession?.isActive ? (
            <div className="rounded-lg border border-border/60 bg-background/50 p-2 text-xs mb-2">
              <div className="space-y-1.5">
                {groupConsecutiveToolCalls(allTools.filter(t => t.status === "completed")).map((group, groupIndex) => {
                  return (
                    <div key={`group-${groupIndex}`} className="flex items-center gap-2">
                      <CheckIcon className="size-3 text-green-500" />
                      <span className="text-foreground">
                        {group.name}
                        {group.count > 1 ? (
                          <span className="ml-1 text-muted-foreground">×{group.count}</span>
                        ) : null}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}

          {/* Main message content */}
          {isAI ? (
            message.content ? (
              <MarkdownContent content={message.content} isStreaming={isStreaming} />
            ) : null
          ) : isEditing ? (
            <div className="space-y-2">
              <textarea
                ref={textareaRef}
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className="w-full min-h-[60px] resize-none rounded-lg bg-background p-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder={t("message.editPlaceholder")}
                rows={3}
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setIsEditing(false)
                    setEditContent(message.content)
                  }}
                  className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-background/80"
                >
                  {t("common.cancel")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (editContent.trim() && onEditMessage) {
                      // For quoted messages, reconstruct the full content with quote
                      if (isQuotedMessage && quotedParts) {
                        const newFullContent = `> ${quotedParts.quotedContent}\n\n${editContent.trim()}`
                        // Only send if content actually changed
                        if (newFullContent !== message.content.trim()) {
                          onEditMessage(newFullContent, messageIndex)
                        }
                      } else {
                        // Regular message - check if content changed
                        if (editContent.trim() !== message.content.trim()) {
                          onEditMessage(editContent.trim(), messageIndex)
                        }
                      }
                    }
                    setIsEditing(false)
                  }}
                  disabled={!editContent.trim() || editDisabled}
                  className="rounded-md bg-primary/20 px-2 py-1 text-xs text-primary hover:bg-primary/30 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {t("message.sendEdit")}
                </button>
              </div>
            </div>
          ) : isQuotedMessage ? (
            // Render quoted message with separator - use user_content for display
            <div className="space-y-2">
              {/* Quoted content - clickable to jump to original, truncated to 100 chars */}
              <button
                type="button"
                onClick={() => {
                  if (quotedMessageId && onJumpToMessage) {
                    onJumpToMessage(quotedMessageId)
                  }
                }}
                disabled={!quotedMessageId || !onJumpToMessage}
                className={cn(
                  "text-sm text-user-bubble-foreground/70 whitespace-pre-wrap break-words text-left w-full",
                  quotedMessageId && onJumpToMessage && "cursor-pointer hover:text-user-bubble-foreground/90 underline underline-offset-2"
                )}
                title={quotedMessageId && onJumpToMessage ? t("message.jumpToOriginal") : undefined}
              >
                {quotedParts ? getTruncatedQuote(quotedParts.quotedContent) : "引用消息"}
              </button>
              {/* Separator line */}
              <Separator className="bg-user-bubble-foreground/30" />
              {/* User content - use user_content from custom_data */}
              <p className="whitespace-pre-wrap break-words text-sm leading-6">
                {userContent}
              </p>
            </div>
          ) : (
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {message.content}
            </p>
          )}
        </MessageContent>

        {/* User message actions: copy, edit, quote - only show on hover */}
        {isUser && !isEditing && isHovered ? (
          <Actions className="pt-1 justify-end">
            <Action
              onClick={() => {
                void handleCopy()
              }}
              className="cursor-pointer"
              tooltip={copied ? t("common.copied") : t("common.copy")}
              label={copied ? t("message.copiedMessage") : t("message.copyMessage")}
            >
              {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
            </Action>
            <Action
              onClick={() => setIsEditing(true)}
              tooltip={t("common.edit")}
              label={t("message.editMessage")}
              className="cursor-pointer"
              disabled={editDisabled}
            >
              <PencilIcon className="size-4" />
            </Action>
            {onQuote ? (
              <Action
                onClick={onQuote}
                tooltip={t("message.quote")}
                label={t("message.quote")}
                className="cursor-pointer"
                disabled={quoteDisabled}
              >
                <QuoteIcon className="size-4" />
              </Action>
            ) : null}
          </Actions>
        ) : null}

        {/* Actions area: copy, thinking process, tool calls */}
        {isAI && !isStreaming ? (
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
              {onQuote ? (
                <Action
                  onClick={onQuote}
                  tooltip={t("message.quote")}
                  label={t("message.quote")}
                  className="cursor-pointer"
                  disabled={quoteDisabled}
                >
                  <QuoteIcon className="size-4" />
                </Action>
              ) : null}
              {/* Single "Agent Process" button - toggles sidebar visibility */}
              {showAgentProcessButton ? (
                <Action
                  onClick={() => {
                    // Toggle sidebar process panel visibility
                    if (onToggleSidebarProcess) {
                      onToggleSidebarProcess()
                    }
                  }}
                  tooltip={t("process.showProcess")}
                  label={t("process.agentProcess")}
                  className="cursor-pointer"
                >
                  <BrainIcon className="size-4" />
                </Action>
              ) : null}
            </Actions>
          </div>
        ) : null}
      </Message>
    </article>
  )
}