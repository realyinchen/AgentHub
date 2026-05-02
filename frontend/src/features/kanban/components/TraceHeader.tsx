/**
 * TraceHeader - Displays trace metadata and summary at the top of the trace page.
 * Style: Flat header, no blur, no glow
 */

import type { AgentTrace } from '../types/trace';
import { formatLatency, formatDate, copyToClipboard } from '../utils/traceUtils';
import { DARK_THEME } from '../styles/theme';

interface TraceHeaderProps {
  trace: AgentTrace;
  onBack?: () => void;
}

export function TraceHeader({ trace, onBack }: TraceHeaderProps) {
  return (
    <div
      className="border-b"
      style={{
        background: 'transparent',
        borderColor: DARK_THEME.border,
      }}
    >
      <div className="px-6 py-4">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-2">
              {onBack && (
                <button
                  onClick={onBack}
                  className="px-3 py-1.5 rounded-md text-sm transition-colors cursor-pointer"
                  style={{
                    background: DARK_THEME.bgPanel,
                    border: `1px solid ${DARK_THEME.border}`,
                    color: DARK_THEME.textSecondary,
                  }}
                >
                  ← Back
                </button>
              )}
              <h1
                className="text-xl font-semibold cursor-pointer transition-colors"
                style={{ color: DARK_THEME.textPrimary }}
                onClick={() => copyToClipboard(trace.title)}
                title="Click to copy"
              >
                {trace.title}
              </h1>
            </div>
            <div
              className="flex items-center gap-4 text-xs font-mono"
              style={{ color: DARK_THEME.textDim }}
            >
              <span>ID: {trace.thread_id}</span>
              <span style={{ color: DARK_THEME.border }}>·</span>
              <span>Generated: {formatDate(trace.generated_at)}</span>
            </div>
          </div>

          {/* Summary Stats */}
          <div className="flex items-center gap-4">
            <StatCard
              value={trace.total_turns}
              label="Turns"
              color={DARK_THEME.textPrimary}
            />
            <Divider />
            <StatCard
              value={trace.total_tool_calls}
              label="Tools"
              color={DARK_THEME.nodeTool}
            />
            <Divider />
            <StatCard
              value={trace.total_subagent_calls}
              label="Subagents"
              color={DARK_THEME.nodeAI}
            />
            <Divider />
            <StatCard
              value={formatLatency(trace.total_latency_ms)}
              label="Total Time"
              color={DARK_THEME.success}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ value, label, color }: { value: string | number; label: string; color: string }) {
  return (
    <div className="text-center">
      <div
        className="text-lg font-bold"
        style={{ color }}
      >
        {value}
      </div>
      <div
        className="text-[10px] uppercase tracking-wide"
        style={{ color: DARK_THEME.textDim }}
      >
        {label}
      </div>
    </div>
  );
}

function Divider() {
  return (
    <div
      className="w-px h-8"
      style={{ background: DARK_THEME.border }}
    />
  );
}