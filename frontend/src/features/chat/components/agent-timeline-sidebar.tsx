import { useEffect, useRef, useState, useCallback } from "react"
import { ChevronDownIcon, ChevronRightIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import type {
  AgentProcessSession,
  AgentProcessStep,
  MessageStep,
  ToolCallEvent,
} from "@/types"
import { useI18n } from "@/i18n"

type AgentTimelineSidebarProps = {
  session: AgentProcessSession | null
  messageSequence: MessageStep[]
  isStreaming: boolean
  selectedSessionId?: string | null  // Filter steps by session
  onClose?: () => void
}

// ==================== Types ====================

type TimelineStepType = "ai_thinking" | "tool" | "ai_final"

type TimelineStep = {
  id: string
  stepNumber: number
  type: TimelineStepType
  title: string
  content: string
  args?: string
  result?: string
  thinking?: string
  toolCalls?: Array<{
    name: string
    args: Record<string, unknown>
  }>
  status: "running" | "done"
  timestamp: number
}

// ==================== Icon Mapping ====================

const STEP_ICONS: Record<TimelineStepType, string> = {
  ai_thinking: "🧠",
  tool: "🔧",
  ai_final: "🧠",
}

// ==================== Sub-components ====================

function LoadingDots() {
  return (
    <span className="inline-flex items-center gap-0.5 ml-1">
      <span className="size-1 rounded-full bg-current animate-bounce [animation-delay:-0.3s]" />
      <span className="size-1 rounded-full bg-current animate-bounce [animation-delay:-0.15s]" />
      <span className="size-1 rounded-full bg-current animate-bounce" />
    </span>
  )
}

function TimelineStepItem({
  step,
  isLast,
  isExpanded,
  onToggle,
}: {
  step: TimelineStep
  isLast: boolean
  isExpanded: boolean
  onToggle: () => void
}) {
  const { t } = useI18n()
  const icon = STEP_ICONS[step.type]
  const isRunning = step.status === "running"

  return (
    <div className="relative">
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
            <LoadingDots />
          ) : (
            <span className="text-green-600 dark:text-green-400 text-[8px]">✔</span>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 pb-2">
          {/* Header - clickable */}
          <button
            type="button"
            onClick={onToggle}
            className="w-full text-left flex items-center gap-1.5 group"
          >
            {/* Expand/Collapse icon */}
            {isExpanded ? (
              <ChevronDownIcon className="size-3 text-gray-400 flex-shrink-0" />
            ) : (
              <ChevronRightIcon className="size-3 text-gray-400 flex-shrink-0" />
            )}

            {/* Icon */}
            <span className="text-xs">{icon}</span>

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
                      <div className="rounded-md bg-amber-50 dark:bg-amber-900/20 p-2 text-[11px] text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-40 overflow-y-auto step-detail-scroll">
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
                      <div className="rounded-md bg-gray-100 dark:bg-gray-800/50 p-2 text-[11px] text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-40 overflow-y-auto step-detail-scroll">
                        {step.content}
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* AI Thinking step during streaming */}
              {step.type === "ai_thinking" && step.thinking && (
                <div className="rounded-md bg-amber-50 dark:bg-amber-900/20 p-2 text-[11px] text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-40 overflow-y-auto step-detail-scroll">
                  {step.thinking}
                </div>
              )}

              {/* Tool calls (for AI messages with tool calls) */}
              {step.toolCalls && step.toolCalls.length > 0 && (
                <div>
                  <div className="text-[9px] text-gray-500 dark:text-gray-400 mb-0.5">
                    {t("process.toolCalls") || "Tool Calls"}
                  </div>
                  <div className="space-y-1">
                    {step.toolCalls.map((tc, idx) => (
                      <div key={idx} className="rounded-md bg-blue-50 dark:bg-blue-900/20 p-2 text-[11px]">
                        <div className="font-medium text-blue-700 dark:text-blue-300">{tc.name}</div>
                        {Object.keys(tc.args).length > 0 && (
                          <pre className="mt-1 text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words">
                            {JSON.stringify(tc.args, null, 2)}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Args (for tool result steps) */}
              {step.args && (
                <div>
                  <div className="text-[9px] text-gray-500 dark:text-gray-400 mb-0.5">
                    {t("process.arguments") || "Arguments"}
                  </div>
                  <div className="rounded-md bg-gray-100 dark:bg-gray-800/50 p-2 text-[11px] text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-32 overflow-y-auto font-mono step-detail-scroll">
                    {step.args}
                  </div>
                </div>
              )}

              {/* Result (for tool result steps) - show directly without "Result" label */}
              {step.result && (
                <div className="rounded-md bg-gray-100 dark:bg-gray-800/50 p-2 text-[11px] text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-40 overflow-y-auto step-detail-scroll">
                  {step.result}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ==================== Main Component ====================

export function AgentTimelineSidebar({
  session,
  messageSequence,
  isStreaming,
  selectedSessionId,
  onClose: _onClose,  // eslint-disable-line @typescript-eslint/no-unused-vars
}: AgentTimelineSidebarProps) {
  const { t } = useI18n()
  const scrollRef = useRef<HTMLDivElement>(null)

  // Track expanded state for each step - default to all collapsed
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())

  // Reset expanded state when message sequence changes (thread switch)
  useEffect(() => {
    setExpandedSteps(new Set())
  }, [messageSequence])

  // Convert message sequence to timeline steps
  const getTimelineStepsFromSequence = useCallback((): TimelineStep[] => {
    if (!messageSequence || messageSequence.length === 0) {
      return []
    }

    // Get all unique session_ids, sorted by first occurrence (which represents chronological order)
    const sessionIds = [...new Set(messageSequence.map(m => m.session_id))]

    // If no sessions, return empty
    if (sessionIds.length === 0) {
      return []
    }

    // Determine which session to show:
    // 1. If selectedSessionId is provided, use that
    // 2. Otherwise, use the latest session (last in the array)
    const targetSessionId = selectedSessionId || sessionIds[sessionIds.length - 1]

    // Filter steps by target session
    const filteredSequence = messageSequence.filter(m => m.session_id === targetSessionId)

    const steps: TimelineStep[] = []

    filteredSequence.forEach((msg) => {
      if (msg.message_type === "tool") {
        // Tool step - show tool name, args, and output
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
        // AI response step (with or without thinking)
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
  }, [messageSequence, selectedSessionId, t])

  // Convert streaming session to timeline steps
  const getTimelineStepsFromSession = useCallback((): TimelineStep[] => {
    if (!session || !session.steps || session.steps.length === 0) {
      return []
    }

    const steps: TimelineStep[] = []

    session.steps.forEach((step) => {
      // Skip human messages - don't show in sidebar
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
        // AI final response
        const thinkingContent = step.thinking || ""
        const hasThinking = thinkingContent.trim().length > 0
        const contentStr = step.content as string || ""
        const hasContent = contentStr.trim().length > 0

        steps.push({
          id: step.id,
          stepNumber: steps.length,
          type: "ai_final",
          title: t("process.llmResponse"),
          content: hasContent ? contentStr : "",
          thinking: hasThinking ? thinkingContent : undefined,
          status: "done",
          timestamp: step.timestamp,
        })
      }
    })

    return steps
  }, [session, t])

  // Determine which steps to show
  const timelineSteps = isStreaming && session?.isActive
    ? getTimelineStepsFromSession()
    : getTimelineStepsFromSequence()

  // Auto-scroll to bottom when new steps arrive
  useEffect(() => {
    if (scrollRef.current && session?.isActive) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [session?.steps, session?.isActive])

  const toggleStep = useCallback((stepId: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev)
      if (next.has(stepId)) {
        next.delete(stepId)
      } else {
        next.add(stepId)
      }
      return next
    })
  }, [])

  // Empty state - no steps to show
  if (timelineSteps.length === 0) {
    return null
  }

  // Streaming mode - show real-time process in a card
  if (isStreaming && session?.isActive) {
    return (
      <div className="space-y-2 p-2 rounded-lg bg-muted/50 border">
        {/* Header */}
        <div className="flex items-center gap-2">
          <div className="size-3 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
          <span className="text-xs font-medium text-muted-foreground">
            {t("process.agentWorking")}
          </span>
        </div>

        {/* Timeline content */}
        <div
          ref={scrollRef}
          className="max-h-80 overflow-y-auto process-steps-scroll"
        >
          <div className="space-y-0">
            {timelineSteps.map((step, index) => (
              <TimelineStepItem
                key={step.id}
                step={step}
                isLast={index === timelineSteps.length - 1}
                isExpanded={expandedSteps.has(step.id)}
                onToggle={() => toggleStep(step.id)}
              />
            ))}
          </div>
        </div>
      </div>
    )
  }

  // History mode - simple card with title, steps always visible
  return (
    <div className="rounded-lg bg-muted/50 border">
      {/* Header - static title */}
      <div className="p-2 flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">
          {t("process.executionSteps")}
        </span>
        <span className="text-[10px] text-muted-foreground">
          {timelineSteps.length}
        </span>
      </div>

      {/* Timeline content */}
      <div
        ref={scrollRef}
        className="px-2 pb-2 max-h-80 overflow-y-auto process-steps-scroll"
      >
        <div className="space-y-0">
          {timelineSteps.map((step, index) => (
            <TimelineStepItem
              key={step.id}
              step={step}
              isLast={index === timelineSteps.length - 1}
              isExpanded={expandedSteps.has(step.id)}
              onToggle={() => toggleStep(step.id)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

// ==================== Hook: useAgentEvents ====================

export function useAgentEvents() {
  const [events, setEvents] = useState<AgentProcessStep[]>([])

  const addEvent = useCallback((event: Omit<AgentProcessStep, "id" | "timestamp">) => {
    const newEvent: AgentProcessStep = {
      ...event,
      id: crypto.randomUUID(),
      timestamp: Date.now(),
    }
    setEvents(prev => [...prev, newEvent])
    return newEvent.id
  }, [])

  const updateEventStatus = useCallback((id: string, status: "running" | "done") => {
    setEvents(prev => prev.map(e =>
      e.id === id ? { ...e, status } : e
    ))
  }, [])

  const clearEvents = useCallback(() => {
    setEvents([])
  }, [])

  return {
    events,
    addEvent,
    updateEventStatus,
    clearEvents,
  }
}

// Re-export with old name for backward compatibility
export { AgentTimelineSidebar as AgentProcessPanel }