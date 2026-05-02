import { useParams, useNavigate } from "react-router-dom"
import { ArrowLeft, Activity, AlertCircle } from "lucide-react"

import { useTraceDetail } from "../hooks/useTrace"
import { TurnCard } from "../components/TurnCard"
import { DARK_THEME } from "../styles/theme"

export function KanbanTracePage() {
  const { threadId } = useParams<{ threadId: string }>()
  const navigate = useNavigate()

  const {
    trace,
    isLoading,
    error,
  } = useTraceDetail(threadId)

  const handleBack = () => navigate("/kanban?tab=conversations")

  if (isLoading) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: DARK_THEME.bgMain }}
      >
        <div className="flex flex-col items-center gap-4">
          <div
            className="w-12 h-12 rounded-full flex items-center justify-center"
            style={{ background: DARK_THEME.nodeAILight }}
          >
            <Activity className="w-6 h-6 animate-pulse" style={{ color: DARK_THEME.nodeAI }} />
          </div>
          <p style={{ color: DARK_THEME.textSecondary }}>Loading...</p>
        </div>
      </div>
    )
  }

  if (error || !trace) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: DARK_THEME.bgMain }}
      >
        <div className="text-center">
          <div
            className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4"
            style={{ background: DARK_THEME.errorLight }}
          >
            <AlertCircle className="w-8 h-8" style={{ color: DARK_THEME.error }} />
          </div>
          <p className="text-lg mb-4" style={{ color: DARK_THEME.error }}>Failed to load</p>
          <button
            onClick={handleBack}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg transition-colors cursor-pointer"
            style={{
              background: DARK_THEME.bgPanel,
              border: `1px solid ${DARK_THEME.border}`,
              color: DARK_THEME.textSecondary,
            }}
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Kanban
          </button>
        </div>
      </div>
    )
  }

  return (
    <div
      className="min-h-screen w-full"
      style={{ background: DARK_THEME.bgMain }}
    >
      {/* Header */}
      <div
        className="border-b"
        style={{ borderColor: DARK_THEME.border }}
      >
        <div className="max-w-3xl mx-auto px-8 py-4">
          <div className="flex items-center gap-4">
            <button
              onClick={handleBack}
              className="flex items-center gap-2 px-3 py-2 rounded-lg transition-colors cursor-pointer"
              style={{
                background: DARK_THEME.bgPanel,
                border: `1px solid ${DARK_THEME.border}`,
                color: DARK_THEME.textSecondary,
              }}
            >
              <ArrowLeft className="w-4 h-4" />
              <span className="text-sm font-medium">Back</span>
            </button>

            <div className="flex items-center gap-3">
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center"
                style={{
                  background: DARK_THEME.nodeAILight,
                  border: `1px solid ${DARK_THEME.borderActive}`,
                }}
              >
                <Activity className="w-4 h-4" style={{ color: DARK_THEME.nodeAI }} />
              </div>
              <div>
                <h1
                  className="text-lg font-semibold"
                  style={{ color: DARK_THEME.textPrimary }}
                >
                  {trace.title}
                </h1>
                <p
                  className="text-xs"
                  style={{ color: DARK_THEME.textDim }}
                >
                  {trace.turns.length} turns · {new Date(trace.generated_at).toLocaleDateString()}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <main className="flex-1 overflow-auto p-6">
        <div className="max-w-3xl mx-auto space-y-4 pb-12">
          {trace.turns.length > 0 ? (
            trace.turns.map((turn, idx) => (
              <TurnCard
                key={turn.turn_id}
                turn={turn}
                turnIndex={idx}
                threadId={threadId}
              />
            ))
          ) : (
            <div className="text-center py-20">
              <div
                className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4"
                style={{ background: 'rgba(255,255,255,0.04)' }}
              >
                <Activity className="w-8 h-8" style={{ color: DARK_THEME.textDim }} />
              </div>
              <p style={{ color: DARK_THEME.textDim }}>
                No turns found in this trace
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}