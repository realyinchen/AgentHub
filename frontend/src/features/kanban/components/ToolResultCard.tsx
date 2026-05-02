/**
 * ToolResultCard - Card displaying a tool result.
 * Style: Flat, solid borders, no glow/blur
 * Shows name, output (collapsible), latency, status.
 */

import { useState } from 'react';
import { ChevronDown, Copy, CheckCircle, XCircle } from 'lucide-react';
import type { ToolResultInfo } from '../types/trace';
import { formatLatency, copyToClipboard } from '../utils/traceUtils';
import { DARK_THEME } from '../styles/theme';

interface ToolResultCardProps {
  toolResult: ToolResultInfo;
  associationColor?: string;
  showIndex?: number;
}

export function ToolResultCard({ toolResult, associationColor, showIndex }: ToolResultCardProps) {
  const [outputExpanded, setOutputExpanded] = useState(false);
  const isLongOutput = toolResult.output.length > 300;
  const isSuccess = toolResult.status === 'success';

  const statusColor = isSuccess ? DARK_THEME.success : DARK_THEME.error;
  const accentColor = associationColor || statusColor;

  return (
    <div
      className="overflow-hidden transition-colors duration-200"
      style={{
        background: DARK_THEME.bgPanel,
        border: `1px solid ${DARK_THEME.border}`,
        borderLeft: `3px solid ${accentColor}`,
        borderRadius: '8px',
      }}
    >
      {/* Header */}
      <div
        className="px-3 py-2 flex items-center justify-between"
        style={{
          background: DARK_THEME.bgHover,
          borderBottom: `1px solid ${DARK_THEME.border}`,
        }}
      >
        <div className="flex items-center gap-2 min-w-0">
          {isSuccess ? (
            <CheckCircle className="w-3.5 h-3.5" style={{ color: statusColor }} />
          ) : (
            <XCircle className="w-3.5 h-3.5" style={{ color: statusColor }} />
          )}
          <span
            className="text-xs font-semibold"
            style={{ color: statusColor }}
          >
            {toolResult.name}
          </span>
          {showIndex !== undefined && (
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded"
              style={{
                background: DARK_THEME.bgPanel,
                color: DARK_THEME.textSecondary,
                border: `1px solid ${DARK_THEME.border}`,
              }}
            >
              #{showIndex + 1}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {toolResult.latency_ms && (
            <span
              className="text-[10px] font-mono"
              style={{ color: DARK_THEME.textDim }}
            >
              {formatLatency(toolResult.latency_ms)}
            </span>
          )}
          <button
            onClick={() => setOutputExpanded(!outputExpanded)}
            className="p-1 rounded transition-colors cursor-pointer"
            style={{ color: DARK_THEME.textDim }}
            title={outputExpanded ? 'Collapse' : 'Expand'}
            onMouseEnter={(e) => e.currentTarget.style.background = DARK_THEME.bgHover}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
          >
            <ChevronDown
              className="w-3 h-3 transition-transform"
              style={{ transform: outputExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
            />
          </button>
        </div>
      </div>

      {/* Output - click to copy */}
      <div
        className="px-3 py-2 text-[11px] font-mono cursor-pointer max-h-40 overflow-auto transition-colors"
        style={{
          color: DARK_THEME.textPrimary,
          background: DARK_THEME.bgMain,
        }}
        onClick={() => copyToClipboard(toolResult.output)}
        title="Click to copy output"
        onMouseEnter={(e) => e.currentTarget.style.background = DARK_THEME.bgHover}
        onMouseLeave={(e) => e.currentTarget.style.background = DARK_THEME.bgMain}
      >
        <div className="flex items-start gap-2">
          <Copy className="w-3 h-3 flex-shrink-0 mt-0.5" style={{ color: DARK_THEME.textDim }} />
          {outputExpanded || !isLongOutput ? (
            <pre className="whitespace-pre-wrap break-all flex-1">{toolResult.output}</pre>
          ) : (
            <span className="flex-1">{toolResult.output.slice(0, 300)}...</span>
          )}
        </div>
      </div>
    </div>
  );
}