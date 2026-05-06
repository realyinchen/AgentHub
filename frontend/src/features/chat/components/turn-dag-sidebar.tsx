/**
 * TurnDAGSidebar - Displays execution DAG for a turn in the sidebar
 * Shows CSSTurnDAG in compact mode, with expandable dialog for full view
 */

import { useState } from "react"
import { Activity, AlertCircle, Maximize2 } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

import CSSTurnDAG from "@/features/kanban/components/dag/CSSTurnDAG"
import { useTurnSteps } from "@/features/kanban/hooks/useTurnSteps"
import { useI18n } from "@/i18n"
import type { MessageStep } from "@/types"

interface TurnDAGSidebarProps {
  /** Current thread ID */
  threadId: string | null
  /** Current session ID (turn) */
  sessionId: string | null
  /** Whether currently streaming */
  isStreaming: boolean
  /** Message sequence for history view */
  messageSequence?: MessageStep[]
}

export function TurnDAGSidebar({
  threadId,
  sessionId,
  isStreaming,
  messageSequence: _messageSequence,
}: TurnDAGSidebarProps) {
  const { t } = useI18n()
  const [isDialogOpen, setIsDialogOpen] = useState(false)

  // Get turn steps for the selected session
  const { steps, loading, error } = useTurnSteps(
    threadId ?? undefined,
    sessionId ?? undefined
  )

  // Determine if we have valid steps to display
  const hasSteps = steps.length > 0
  const isLoading = loading || (isStreaming && !hasSteps)

  // Dialog steps: use same steps, no loading state for dialog
  const dialogSteps = steps

  // Calculate step count for header
  const stepCount = steps.length
  const toolCallCount = steps.filter(s => s.message_type === 'tool').length
  const hasThinking = steps.some(s =>
    s.message_type === 'ai' && s.thinking && s.thinking.trim().length > 0
  )

  // Loading state - simple loading animation
  if (isLoading) {
    return (
      <div
        className="rounded-2xl bg-muted/30 border border-border/50 overflow-hidden backdrop-blur-sm shadow-lg"
      >
        {/* Header */}
        <div className="p-3 flex items-center justify-between border-b border-border/30 bg-muted/20">
          <div className="flex items-center gap-2">
            <div className="size-6 rounded-lg bg-accent/15 flex items-center justify-center">
              <div className="size-3 rounded-full border-2 border-primary border-t-transparent animate-spin" />
            </div>
            <span className="text-sm font-semibold text-foreground">
              {t("process.agentWorking") || "Agent working..."}
            </span>
          </div>
        </div>

        {/* Simple loading */}
        <div className="p-8 flex justify-center">
          <div className="size-6 rounded-full border-2 border-primary/30 border-t-primary animate-spin" />
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div
        className="rounded-2xl bg-muted/30 border border-border/50 overflow-hidden backdrop-blur-sm shadow-lg"
      >
        <div className="p-3 flex items-center justify-between border-b border-border/30 bg-muted/20">
          <div className="flex items-center gap-2">
            <div className="size-6 rounded-lg bg-destructive/15 flex items-center justify-center">
              <AlertCircle className="size-3.5 text-destructive" />
            </div>
            <span className="text-sm font-semibold text-foreground">
              {t("process.executionSteps") || "Execution Steps"}
            </span>
          </div>
        </div>
        <div className="p-6 flex flex-col items-center justify-center text-center">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      </div>
    )
  }

  // Empty state - no steps available
  if (!hasSteps) {
    return (
      <div
        className="rounded-2xl bg-muted/30 border border-border/50 overflow-hidden backdrop-blur-sm shadow-lg"
      >
        <div className="p-3 flex items-center justify-between border-b border-border/30 bg-muted/20">
          <div className="flex items-center gap-2">
            <div className="size-6 rounded-lg bg-accent/15 flex items-center justify-center">
              <Activity className="size-3.5 text-accent" />
            </div>
            <span className="text-sm font-semibold text-foreground">
              {t("process.executionSteps") || "Execution Steps"}
            </span>
          </div>
        </div>
        <div className="p-6 flex flex-col items-center justify-center text-center">
          <div className="size-12 rounded-full bg-muted/40 flex items-center justify-center mb-3">
            <Activity className="size-6 text-muted-foreground/50" />
          </div>
          <p className="text-sm text-muted-foreground">
            {t("process.noSteps") || "No execution steps available"}
          </p>
          <p className="text-xs text-muted-foreground/50 mt-1">
            {t("process.noStepsHint") || "This session has no recorded steps"}
          </p>
        </div>
      </div>
    )
  }

  // Normal state - show DAG
  return (
    <>
      <div
        className="rounded-2xl bg-muted/30 border border-border/50 overflow-hidden backdrop-blur-sm shadow-lg flex flex-col h-full"
      >
        {/* Header */}
        <div className="p-3 flex items-center justify-between border-b border-border/30 bg-muted/20">
          <div className="flex items-center gap-2">
            <div className="size-6 rounded-lg bg-accent/15 flex items-center justify-center">
              <Activity className="size-3.5 text-accent" />
            </div>
            <span className="text-sm font-semibold text-foreground">
              {t("process.executionSteps") || "Execution Steps"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsDialogOpen(true)}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
              title={t("process.viewFullGraph") || "View full graph"}
            >
              <Maximize2 className="size-4" />
            </button>
            <span className="text-xs font-medium text-muted-foreground bg-muted/50 px-2 py-0.5 rounded-full">
              {stepCount}
            </span>
          </div>
        </div>

        {/* DAG container - compact mode, fills available space */}
        <div className="flex-1 min-h-0 p-2">
          <CSSTurnDAG steps={steps} compact={true} className="w-full h-full" />
        </div>
      </div>

      {/* Full DAG Dialog */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-w-4xl w-[90vw] max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {t("process.executionSteps") || "Execution Steps"}
              <span className="text-sm font-normal text-muted-foreground">
                ({stepCount} steps)
              </span>
            </DialogTitle>
          </DialogHeader>

          <div className="flex-1 overflow-auto">
            <CSSTurnDAG steps={dialogSteps} compact={false} className="w-full min-h-[400px]" />
          </div>

          {/* Summary footer for dialog */}
          <div className="flex items-center gap-4 text-xs text-muted-foreground pt-2 border-t border-border/50">
            <span>{stepCount} steps</span>
            <span>·</span>
            <span>{toolCallCount} tool calls</span>
            {hasThinking && (
              <>
                <span>·</span>
                <span>thinking</span>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}