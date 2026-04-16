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
  ai_final: "✨",
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
        <div className="absolute left-[11px] top-6 bottom-0 w-0.5 bg-gray-200 dark:bg-gray-700" />
      )}

      {/* Step row */}
      <div className="flex items-start gap-2">
        {/* Dot/Circle */}
        <div
          className={cn(
            "flex-shrink-0 size-6 rounded-full flex items-center justify-center text-xs z-10",
            isRunning
              ? "bg-blue-100 dark:bg-blue-900/30 animate-pulse"
              : "bg-green-100 dark:bg-green-900/30"
          )}
        >
          {isRunning ? (
            <LoadingDots />
          ) : (
            <span className="text-green-600 dark:text-green-400">✔</span>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 pb-3">
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
            <span className="text-sm">{icon}</span>

            {/* Title */}
            <span className="text-xs font-medium text-gray-700 dark:text-gray-300 truncate flex-1">
              {step.title}
            </span>
          </button>

          {/* Expandable content */}
          {isExpanded && (
            <div className="mt-1.5 ml-5 space-y-2">
              {/* Thinking content (for AI messages with thinking) */}
              {step.thinking && (
                <div>
                  <div className="text-[10px] text-gray-500 dark:text-gray-400 mb-0.5">
                    {t("process.thinking") || "Thinking"}
                  </div>
                  <div className="rounded-md bg-amber-50 dark:bg-amber-900/20 p-2 text-xs text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-60 overflow-y-auto">
                    {step.thinking}
                  </div>
                </div>
              )}

              {/* Tool calls (for AI messages with tool calls) */}
              {step.toolCalls && step.toolCalls.length > 0 && (
                <div>
                  <div className="text-[10px] text-gray-500 dark:text-gray-400 mb-0.5">
                    {t("process.toolCalls") || "Tool Calls"}
                  </div>
                  <div className="space-y-1">
                    {step.toolCalls.map((tc, idx) => (
                      <div key={idx} className="rounded-md bg-blue-50 dark:bg-blue-900/20 p-2 text-xs">
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
                  <div className="text-[10px] text-gray-500 dark:text-gray-400 mb-0.5">
                    {t("process.arguments") || "Arguments"}
                  </div>
                  <div className="rounded-md bg-gray-100 dark:bg-gray-800/50 p-2 text-xs text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-40 overflow-y-auto font-mono">
                    {step.args}
                  </div>
                </div>
              )}

              {/* Result (for tool result steps) */}
              {step.result && (
                <div>
                  <div className="text-[10px] text-gray-500 dark:text-gray-400 mb-0.5">
                    {t("process.result") || "Result"}
                  </div>
                  <div className="rounded-md bg-gray-100 dark:bg-gray-800/50 p-2 text-xs text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-60 overflow-y-auto">
                    {step.result}
                  </div>
                </div>
              )}

              {/* Main content (for human messages or AI final response) */}
              {step.content && !step.toolCalls?.length && !step.thinking && (
                <div className="rounded-md bg-gray-100 dark:bg-gray-800/50 p-2 text-xs text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-words max-h-60 overflow-y-auto">
                  {step.content || <span className="text-gray-400 italic">{t("process.noContent")}</span>}
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
  onClose,
}: AgentTimelineSidebarProps) {
  const { t } = useI18n()
  const scrollRef = useRef<HTMLDivElement>(null)

  // Track expanded state for each step
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

    const steps: TimelineStep[] = []

    messageSequence.forEach((msg) => {
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
          title: t("process.llmResponse"),
          content: hasContent ? contentStr : "",
          thinking: hasThinking ? thinkingContent : undefined,
          status: "done",
          timestamp: Date.now(),
        })
      }
    })

    return steps
  }, [messageSequence, t])

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

  // Streaming mode - show real-time process
  if (isStreaming && session?.isActive) {
    return (
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="flex items-center gap-2 px-1 py-2 border-b border-gray-200 dark:border-gray-700 mb-2">
          <div className="size-4 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
            {t("process.agentWorking")}
          </span>
        </div>

        {/* Timeline content */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-1"
        >
          {timelineSteps.length === 0 ? (
            <div className="flex items-center gap-2 text-xs text-gray-500 py-4">
              <LoadingDots />
              <span>{t("process.starting")}</span>
            </div>
          ) : (
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
          )}
        </div>
      </div>
    )
  }

  // History mode - show message sequence from backend
  if (timelineSteps.length > 0) {
    return (
      <div className="flex flex-col h-full">
        {/* Header with close button */}
        <div className="flex items-center justify-between px-1 py-2 border-b border-gray-200 dark:border-gray-700 mb-2">
          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
            {t("process.processDetails")}
          </span>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            >
              {t("common.close")}
            </button>
          )}
        </div>

        {/* Timeline content */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-1"
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

  // Empty state - no active session or historical data
  return null
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