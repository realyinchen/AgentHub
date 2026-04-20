import { useEffect, useRef, useState, useCallback } from "react"
import { ChevronDownIcon, Sparkles, Wrench, Brain, CheckCircle2, Maximize2 } from "lucide-react"

import { cn } from "@/lib/utils"
import type {
  AgentProcessSession,
  AgentProcessStep,
  MessageStep,
  ToolCallEvent,
} from "@/types"
import { useI18n } from "@/i18n"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

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

// ==================== Sub-components ====================

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
  const isRunning = step.status === "running"

  // Get icon based on type
  const getIcon = () => {
    switch (step.type) {
      case "ai_thinking":
        return <Brain className="size-3.5" />
      case "tool":
        return <Wrench className="size-3.5" />
      case "ai_final":
        return <Sparkles className="size-3.5" />
    }
  }

  return (
    <div className="relative">
      {/* Timeline vertical line */}
      {!isLast && (
        <div className="absolute left-[15px] top-8 bottom-0 w-0.5 bg-gradient-to-b from-primary/30 to-transparent" />
      )}

      {/* Step row */}
      <div className="flex items-start gap-3">
        {/* Dot/Circle - 简洁的圆圈配勾号，无光环 */}
        <div
          className={cn(
            "flex-shrink-0 size-6 rounded-full flex items-center justify-center z-10 border border-muted-foreground/30",
            isRunning
              ? "bg-primary/20 dark:bg-primary/30 animate-pulse"
              : "bg-transparent"
          )}
        >
          {isRunning ? (
            <div className="text-primary dark:text-primary">
              {getIcon()}
            </div>
          ) : (
            <CheckCircle2 className="size-4 text-primary" />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 pb-3 w-full">
          {/* Header - clickable - 点击步骤名称即可展开/收起 */}
          <button
            type="button"
            onClick={onToggle}
            className="w-full text-left flex items-center gap-2 group"
          >
            {/* Icon */}
            <div className={cn(
              "size-6 rounded-lg flex items-center justify-center transition-all duration-200",
              step.type === "ai_thinking" && "bg-amber-500/15 text-amber-600 dark:text-amber-400",
              step.type === "tool" && "bg-blue-500/15 text-blue-600 dark:text-blue-400",
              step.type === "ai_final" && "bg-primary/15 text-primary"
            )}>
              {getIcon()}
            </div>

            {/* Title */}
            <span className="text-sm font-medium text-foreground/90 group-hover:text-foreground truncate flex-1 transition-colors">
              {step.title}
            </span>

            {/* Expand/Collapse indicator */}
            <ChevronDownIcon className={cn(
              "size-4 text-muted-foreground/50 transition-transform duration-200",
              isExpanded && "rotate-180"
            )} />
          </button>

          {/* Expandable content - 尽可能宽地展示 */}
          {isExpanded && (
            <div className="mt-2 -ml-2 -mr-1 space-y-2 animate-in slide-in-from-top-2 duration-200 w-full max-w-none">
              {/* AI Thinking step - show reasoning and content in separate blocks */}
              {step.type === "ai_final" && (step.thinking || step.content) && (
                <>
                  {/* Reasoning block */}
                  {step.thinking && (
                    <div className="rounded-xl overflow-hidden">
                      <div className="text-[10px] text-muted-foreground px-3 py-1.5 bg-amber-500/10 font-medium uppercase tracking-wider">
                        {t("process.reasoning") || "Reasoning"}
                      </div>
                      <div className="bg-amber-500/5 dark:bg-amber-500/10 px-3 py-2 text-xs text-muted-foreground whitespace-pre-wrap break-words max-h-40 overflow-y-auto step-detail-scroll border border-amber-500/10 rounded-b-xl">
                        {step.thinking}
                      </div>
                    </div>
                  )}

                  {/* Content block */}
                  {step.content && (
                    <div className="rounded-xl overflow-hidden">
                      <div className="text-[10px] text-muted-foreground px-3 py-1.5 bg-primary/10 font-medium uppercase tracking-wider">
                        {t("process.content") || "Content"}
                      </div>
                      <div className="bg-muted/50 px-3 py-2 text-xs text-muted-foreground whitespace-pre-wrap break-words max-h-40 overflow-y-auto step-detail-scroll border border-border/50 rounded-b-xl">
                        {step.content}
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* AI Thinking step during streaming */}
              {step.type === "ai_thinking" && step.thinking && (
                <div className="rounded-xl bg-amber-500/5 dark:bg-amber-500/10 p-3 text-xs text-muted-foreground whitespace-pre-wrap break-words max-h-40 overflow-y-auto step-detail-scroll border border-amber-500/10">
                  {step.thinking}
                </div>
              )}

              {/* Tool calls (for AI messages with tool calls) */}
              {step.toolCalls && step.toolCalls.length > 0 && (
                <div className="rounded-xl overflow-hidden">
                  <div className="text-[10px] text-muted-foreground px-3 py-1.5 bg-blue-500/10 font-medium uppercase tracking-wider">
                    {t("process.toolCalls") || "Tool Calls"}
                  </div>
                  <div className="space-y-1.5 p-2">
                    {step.toolCalls.map((tc, idx) => (
                      <div key={idx} className="rounded-lg bg-blue-500/5 dark:bg-blue-500/10 p-2.5 text-xs border border-blue-500/10">
                        <div className="font-semibold text-blue-600 dark:text-blue-400">{tc.name}</div>
                        {Object.keys(tc.args).length > 0 && (
                          <pre className="mt-1.5 text-muted-foreground whitespace-pre-wrap break-words font-mono text-[11px]">
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
                <div className="rounded-xl overflow-hidden">
                  <div className="text-[10px] text-muted-foreground px-3 py-1.5 bg-muted/50 font-medium uppercase tracking-wider">
                    {t("process.arguments") || "Arguments"}
                  </div>
                  <div className="bg-muted/30 px-3 py-2 text-xs text-muted-foreground whitespace-pre-wrap break-words max-h-32 overflow-y-auto font-mono step-detail-scroll border border-border/30 rounded-b-xl">
                    {step.args}
                  </div>
                </div>
              )}

              {/* Result (for tool result steps) - show directly without "Result" label */}
              {step.result && (
                <div className="rounded-xl bg-muted/30 p-3 text-xs text-muted-foreground whitespace-pre-wrap break-words max-h-40 overflow-y-auto step-detail-scroll border border-border/30">
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
  
  // Track expanded state for the modal view
  const [expandedStepsInModal, setExpandedStepsInModal] = useState<Set<string>>(new Set())
  
  // Modal open state
  const [isModalOpen, setIsModalOpen] = useState(false)

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
  
  // Toggle step in modal
  const toggleStepInModal = useCallback((stepId: string) => {
    setExpandedStepsInModal(prev => {
      const next = new Set(prev)
      if (next.has(stepId)) {
        next.delete(stepId)
      } else {
        next.add(stepId)
      }
      return next
    })
  }, [])
  
  // Open modal and expand all steps
  const openExpandedView = useCallback(() => {
    // Expand all steps when opening modal
    const allStepIds = new Set(timelineSteps.map(s => s.id))
    setExpandedStepsInModal(allStepIds)
    setIsModalOpen(true)
  }, [timelineSteps])

  // Empty state - no steps to show
  if (timelineSteps.length === 0) {
    return null
  }

  // Streaming mode - show real-time process in a card
  if (isStreaming && session?.isActive) {
    return (
      <div className="space-y-3 p-3 rounded-2xl bg-gradient-to-br from-primary/5 to-accent/5 
                      border border-primary/20 backdrop-blur-sm
                      shadow-[0_0_20px_rgba(0,209,255,0.1)] dark:shadow-[0_0_20px_rgba(0,209,255,0.05)]">
        {/* Header */}
        <div className="flex items-center gap-2.5">
          <div className="relative">
            <div className="size-4 rounded-full border-2 border-primary border-t-transparent animate-spin" />
            <div className="absolute inset-0 size-4 rounded-full bg-primary/20 animate-ping" />
          </div>
          <span className="text-sm font-semibold text-foreground">
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
    <>
      <div className="rounded-2xl bg-muted/30 border border-border/50 overflow-hidden
                      backdrop-blur-sm shadow-lg">
        {/* Header - static title */}
        <div className="p-3 flex items-center justify-between border-b border-border/30 bg-muted/20">
          <div className="flex items-center gap-2">
            <div className="size-6 rounded-lg bg-accent/15 flex items-center justify-center">
              <CheckCircle2 className="size-3.5 text-accent" />
            </div>
            <span className="text-sm font-semibold text-foreground">
              {t("process.executionSteps")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={openExpandedView}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
              title={t("process.expandView") || "Expand view"}
            >
              <Maximize2 className="size-4" />
            </button>
            <span className="text-xs font-medium text-muted-foreground bg-muted/50 px-2 py-0.5 rounded-full">
              {timelineSteps.length}
            </span>
          </div>
        </div>

        {/* Timeline content */}
        <div
          ref={scrollRef}
          className="p-3 max-h-80 overflow-y-auto process-steps-scroll"
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

      {/* Expanded modal */}
      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>{t("process.executionSteps")}（{timelineSteps.length}）</DialogTitle>
          </DialogHeader>
          
          <div className="flex-1 overflow-y-auto process-steps-scroll">
            <div className="space-y-0 p-1">
              {timelineSteps.map((step, index) => (
                <TimelineStepItem
                  key={step.id}
                  step={step}
                  isLast={index === timelineSteps.length - 1}
                  isExpanded={expandedStepsInModal.has(step.id)}
                  onToggle={() => toggleStepInModal(step.id)}
                />
              ))}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
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