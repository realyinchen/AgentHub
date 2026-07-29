/**
 * TurnDAGSidebar - Displays execution DAG for a turn in the sidebar
 * Shows CSSTurnDAG in compact mode, with expandable dialog for full view
 * 
 * Displays DAG by requestId - each request corresponds to one AI message turn.
 */

import { useState, useEffect } from "react"
import { Activity, AlertCircle, Maximize2 } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

import CSSTurnDAG from "@/features/kanban/components/dag/CSSTurnDAG"
import { SciFiLoader } from "@/components/ai/neural-network-loader"
import { useI18n } from "@/i18n"
import type { ExecutionDagRaw } from "@/features/kanban/types/dag"
import { getCurrentUserId } from "@/lib/api"

// API base URL - same origin
const API_BASE_URL = "/api/v1"

interface TurnDAGSidebarProps {
  /** Current thread ID */
  threadId: string | null
  /** Whether currently streaming */
  isStreaming: boolean
  /** Request ID for viewing DAG (each request = one AI turn) */
  requestId?: string | null
}

// Hook to fetch DAG by request_id
function useDagByRequestId(threadId: string | null, requestId: string | null | undefined) {
  const [dag, setDag] = useState<ExecutionDagRaw | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!threadId || !requestId) {
      setDag(null)
      return
    }

    setLoading(true)
    setError(null)

    const controller = new AbortController()

    async function fetchDag() {
      try {
        const userId = getCurrentUserId()
        if (!userId) {
          throw new Error('No user selected')
        }
        const response = await fetch(
          `${API_BASE_URL}/traces/${threadId}/dag/${requestId}?user_id=${encodeURIComponent(userId)}`,
          { signal: controller.signal }
        )
        if (!response.ok) {
          throw new Error(`Failed to fetch DAG: ${response.status}`)
        }
        const data = await response.json() as ExecutionDagRaw
        setDag(data)
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          return
        }
        setError(err instanceof Error ? err.message : 'Failed to fetch DAG')
      } finally {
        setLoading(false)
      }
    }

    void fetchDag()

    return () => {
      controller.abort()
    }
  }, [threadId, requestId])

  return { dag, loading, error }
}

export function TurnDAGSidebar({
  threadId,
  isStreaming,
  requestId,
}: TurnDAGSidebarProps) {
  const { t } = useI18n()
  const [isDialogOpen, setIsDialogOpen] = useState(false)

  // Fetch DAG by request_id
  const { dag: fetchedDag, loading: fetchedLoading, error } = useDagByRequestId(threadId, requestId)

  // IMPORTANT: During streaming, always show loading state
  // - Don't show stale data from previous turn
  // - Only fetch and display DAG after streaming ends
  const dag = isStreaming ? null : fetchedDag
  const loading = isStreaming || fetchedLoading

  // Determine if we have valid steps to display
  const hasSteps = Boolean(dag && (dag.execution_graph?.nodes.length || dag.nodes.length))

  // Calculate step count for header
  const stepCount = dag?.execution_graph?.nodes.length || dag?.nodes.length || 0

  // Loading state - use SciFiLoader animation
  if (loading) {
    return (
      <div
        className="rounded-2xl bg-muted/30 border border-border/50 overflow-hidden backdrop-blur-sm shadow-lg"
      >
        {/* Header */}
        <div className="p-3 flex items-center justify-between border-b border-border/30 bg-muted/20">
          <div className="flex items-center gap-2">
            <div className="size-6 rounded-lg bg-accent/15 flex items-center justify-center">
              <Activity className="size-3.5 text-accent animate-pulse" />
            </div>
            <span className="text-sm font-semibold text-foreground">
              {t("process.agentWorking") || "Agent working..."}
            </span>
          </div>
        </div>

        {/* Neural network loader */}
        <div className="p-6 flex justify-center">
          <SciFiLoader className="w-32 h-32" showText={false} />
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
        className="rounded-2xl bg-muted/30 border border-border/50 overflow-hidden backdrop-blur-sm shadow-lg flex flex-col h-full animate-in fade-in duration-500"
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
          {dag && <CSSTurnDAG dag={dag} compact={true} className="w-full h-full" />}
        </div>
      </div>

      {/* Full DAG Dialog */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-w-4xl w-[90vw] max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {t("process.executionSteps") || "Execution Steps"}
            </DialogTitle>
          </DialogHeader>

          <div className="flex-1 overflow-auto">
            {dag && <CSSTurnDAG dag={dag} compact={false} className="w-full min-h-[400px]" />}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
