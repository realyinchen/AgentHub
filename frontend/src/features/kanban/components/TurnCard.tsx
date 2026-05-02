/**
 * TurnCard - Core Kanban card for one agent turn
 * Style: Flat panel, clean info hierarchy
 */

import { useState } from 'react';
import { ChevronRight, ChevronDown, Brain } from 'lucide-react';
import type { AgentTurn } from '../types/trace';
import { formatLatency, truncateText } from '../utils/traceUtils';
import CSSTurnDAG from './dag/CSSTurnDAG';
import { useTurnSteps } from '../hooks/useTurnSteps';
import { DARK_THEME } from '../styles/theme';

interface TurnCardProps {
  turn: AgentTurn;
  turnIndex: number;
  threadId?: string;
}

export function TurnCard({ turn, turnIndex, threadId }: TurnCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const { steps, loading, error } = useTurnSteps(threadId, turn.session_id ?? undefined);

  const hasThinking = !!turn.aiMsg?.thinking;
  const hasFinalResponse = !!turn.aiFinalResponse?.content;
  const totalToolCalls = turn.toolMsgs.length;

  return (
    <div
      className="overflow-hidden transition-colors"
      style={{
        background: DARK_THEME.bgPanel,
        border: `1px solid ${DARK_THEME.border}`,
        borderRadius: '12px',
      }}
    >
      {/* Header */}
      <div
        className="px-5 py-4 flex items-center justify-between cursor-pointer transition-colors"
        style={{
          background: 'transparent',
          borderBottom: isExpanded ? `1px solid ${DARK_THEME.border}` : 'none',
        }}
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3 flex-1">
          <div
            className="flex items-center justify-center w-7 h-7 rounded-md text-sm font-semibold"
            style={{
              background: DARK_THEME.nodeAILight,
              border: `1px solid ${DARK_THEME.nodeAIBorder}`,
              color: DARK_THEME.nodeAI,
            }}
          >
            {turnIndex + 1}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm truncate" style={{ color: DARK_THEME.textPrimary }}>
              👤 {truncateText(turn.humanMsg, 60)}
            </div>
            <div className="text-xs mt-1 flex items-center gap-2" style={{ color: DARK_THEME.textSecondary }}>
              {hasThinking && (
                <span className="inline-flex items-center gap-1" style={{ color: DARK_THEME.nodeAI }}>
                  <Brain className="w-3 h-3" />thinking
                </span>
              )}
              {totalToolCalls > 0 && (
                <span style={{ color: DARK_THEME.nodeTool }}>{totalToolCalls} tools</span>
              )}
              {hasFinalResponse && (
                <span style={{ color: DARK_THEME.success }}>→ ✅</span>
              )}
              {!hasFinalResponse && totalToolCalls === 0 && !hasThinking && (
                <span style={{ color: DARK_THEME.nodeAI }}>→ AI</span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-4 text-sm flex-shrink-0">
          {turn.aiMsg?.model_name && (
            <span
              className="font-mono text-xs px-2 py-1 rounded-md"
              style={{
                background: 'rgba(255,255,255,0.04)',
                border: `1px solid ${DARK_THEME.border}`,
                color: DARK_THEME.textSecondary,
              }}
            >
              {turn.aiMsg.model_name}
            </span>
          )}
          <span style={{ color: DARK_THEME.textSecondary, fontVariantNumeric: 'tabular-nums' }}>
            {formatLatency(turn.total_latency_ms)}
          </span>
          <button
            onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}
            className="p-2 rounded-md transition-colors cursor-pointer"
            style={{ background: 'rgba(255,255,255,0.04)', border: `1px solid ${DARK_THEME.border}` }}
          >
            {isExpanded
              ? <ChevronDown className="w-5 h-5" style={{ color: DARK_THEME.textPrimary }} />
              : <ChevronRight className="w-5 h-5" style={{ color: DARK_THEME.textSecondary }} />
            }
          </button>
        </div>
      </div>

      {/* Content - DAG View */}
      {isExpanded && (
        <div className="p-4" style={{ background: DARK_THEME.bgMain }}>
          {loading && (
            <div className="flex items-center justify-center h-[300px]" style={{ color: DARK_THEME.textSecondary }}>
              Loading execution graph...
            </div>
          )}
          {error && (
            <div className="flex items-center justify-center h-[200px]" style={{ color: DARK_THEME.error }}>
              Error: {error}
            </div>
          )}
          {!loading && !error && steps.length > 0 && <CSSTurnDAG steps={steps} />}
          {!loading && !error && steps.length === 0 && (
            <div className="flex items-center justify-center h-[200px]" style={{ color: DARK_THEME.textDim }}>
              No execution steps available
            </div>
          )}
        </div>
      )}
    </div>
  );
}