/**
 * ToolCallCard - Card displaying a tool call.
 * Style: Flat, solid borders, no glow/blur
 * Shows name + args (collapsible JSON).
 */

import { useState, useMemo } from 'react';
import { ChevronDown, Copy } from 'lucide-react';
import type { ToolCall } from '../types/trace';
import { copyToClipboard } from '../utils/traceUtils';
import { DARK_THEME } from '../styles/theme';

interface ToolCallCardProps {
  toolCall: ToolCall;
  associationColor?: string;
  showIndex?: number;
}

export function ToolCallCard({ toolCall, associationColor, showIndex }: ToolCallCardProps) {
  const [argsExpanded, setArgsExpanded] = useState(false);
  const argsJson = useMemo(() => JSON.stringify(toolCall.args, null, 2), [toolCall.args]);
  const isLongArgs = argsJson.length > 200;

  const accentColor = associationColor || DARK_THEME.nodeTool;

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
          <span
            className="text-xs font-semibold"
            style={{ color: accentColor }}
          >
            {toolCall.name}
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
        <button
          onClick={() => setArgsExpanded(!argsExpanded)}
          className="p-1 rounded transition-colors cursor-pointer"
          style={{ color: DARK_THEME.textDim }}
          title={argsExpanded ? 'Collapse' : 'Expand'}
          onMouseEnter={(e) => e.currentTarget.style.background = DARK_THEME.bgHover}
          onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
        >
          <ChevronDown
            className="w-3 h-3 transition-transform"
            style={{ transform: argsExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
          />
        </button>
      </div>

      {/* Arguments - click to copy */}
      <div
        className="px-3 py-2 text-[11px] font-mono cursor-pointer max-h-32 overflow-auto transition-colors"
        style={{
          color: DARK_THEME.textPrimary,
          background: DARK_THEME.bgMain,
        }}
        onClick={() => copyToClipboard(argsJson)}
        title="Click to copy JSON"
        onMouseEnter={(e) => e.currentTarget.style.background = DARK_THEME.bgHover}
        onMouseLeave={(e) => e.currentTarget.style.background = DARK_THEME.bgMain}
      >
        <div className="flex items-start gap-2">
          <Copy className="w-3 h-3 flex-shrink-0 mt-0.5" style={{ color: DARK_THEME.textDim }} />
          {argsExpanded || !isLongArgs ? (
            <pre className="whitespace-pre-wrap break-all flex-1">{argsJson}</pre>
          ) : (
            <span className="flex-1">{argsJson.slice(0, 200)}...</span>
          )}
        </div>
      </div>
    </div>
  );
}