/**
 * SubagentCard - Card displaying a subagent run.
 * Style: Flat, solid borders, no glow/blur
 * Defaults to collapsed, showing summary only. Expand to see Input/Output.
 */

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import type { SubagentRun } from '../types/trace';
import { formatLatency, copyToClipboard } from '../utils/traceUtils';
import { DARK_THEME } from '../styles/theme';

interface SubagentCardProps {
  subagent: SubagentRun;
}

export function SubagentCard({ subagent }: SubagentCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [inputExpanded, setInputExpanded] = useState(false);
  const [outputExpanded, setOutputExpanded] = useState(false);

  const isLongInput = subagent.input.length > 300;
  const isLongOutput = subagent.output.length > 300;

  const stepLabel = subagent.step_count !== undefined
    ? `${subagent.step_count} step${subagent.step_count !== 1 ? 's' : ''}`
    : null;

  return (
    <div
      className="overflow-hidden transition-colors duration-200"
      style={{
        background: DARK_THEME.bgPanel,
        border: `1px solid ${DARK_THEME.border}`,
        borderLeft: `3px solid ${DARK_THEME.nodeAI}`,
        borderRadius: '8px',
      }}
    >
      {/* Summary Row (always visible) */}
      <div
        className="px-3 py-2.5 cursor-pointer flex items-center justify-between transition-colors duration-200"
        onClick={() => setIsExpanded(!isExpanded)}
        onMouseEnter={(e) => e.currentTarget.style.background = DARK_THEME.bgHover}
        onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="text-xs font-semibold"
            style={{ color: DARK_THEME.nodeAI }}
          >
            Subagent: {subagent.name}
          </span>
          <span
            className="text-[10px]"
            style={{ color: DARK_THEME.textDim }}
          >
            ({[stepLabel, formatLatency(subagent.latency_ms)].filter(Boolean).join(', ')})
          </span>
        </div>
        <ChevronDown
          className="w-3 h-3 transition-transform"
          style={{
            color: DARK_THEME.textDim,
            transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
          }}
        />
      </div>

      {/* Expanded Content: Input + Output */}
      {isExpanded && (
        <div
          className="px-3 pb-3 space-y-2 pt-2"
          style={{ borderTop: `1px solid ${DARK_THEME.border}` }}
        >
          {/* Input Section */}
          <div
            className="overflow-hidden"
            style={{
              border: `1px solid ${DARK_THEME.border}`,
              borderRadius: '6px',
            }}
          >
            <div
              className="px-2 py-1.5 flex items-center justify-between cursor-pointer transition-colors"
              style={{ background: DARK_THEME.bgHover }}
              onClick={() => setInputExpanded(!inputExpanded)}
              onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.06)'}
              onMouseLeave={(e) => e.currentTarget.style.background = DARK_THEME.bgHover}
            >
              <span
                className="text-[10px] font-semibold"
                style={{ color: DARK_THEME.textSecondary }}
              >
                Input
              </span>
              <ChevronDown
                className="w-2.5 h-2.5 transition-transform"
                style={{
                  color: DARK_THEME.textDim,
                  transform: inputExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                }}
              />
            </div>
            <div
              className="px-2 py-1.5 text-[10px] font-mono cursor-pointer max-h-32 overflow-auto transition-colors"
              style={{
                color: DARK_THEME.textPrimary,
                background: DARK_THEME.bgMain,
              }}
              onClick={() => copyToClipboard(subagent.input)}
              title="Click to copy input"
              onMouseEnter={(e) => e.currentTarget.style.background = DARK_THEME.bgHover}
              onMouseLeave={(e) => e.currentTarget.style.background = DARK_THEME.bgMain}
            >
              {inputExpanded || !isLongInput ? (
                <pre className="whitespace-pre-wrap break-all">{subagent.input}</pre>
              ) : (
                <span>{subagent.input.slice(0, 300)}...</span>
              )}
            </div>
          </div>

          {/* Output Section */}
          <div
            className="overflow-hidden"
            style={{
              border: `1px solid ${DARK_THEME.border}`,
              borderRadius: '6px',
            }}
          >
            <div
              className="px-2 py-1.5 flex items-center justify-between cursor-pointer transition-colors"
              style={{ background: DARK_THEME.bgHover }}
              onClick={() => setOutputExpanded(!outputExpanded)}
              onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.06)'}
              onMouseLeave={(e) => e.currentTarget.style.background = DARK_THEME.bgHover}
            >
              <span
                className="text-[10px] font-semibold"
                style={{ color: DARK_THEME.textSecondary }}
              >
                Output
              </span>
              <ChevronDown
                className="w-2.5 h-2.5 transition-transform"
                style={{
                  color: DARK_THEME.textDim,
                  transform: outputExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                }}
              />
            </div>
            <div
              className="px-2 py-1.5 text-[10px] font-mono cursor-pointer max-h-32 overflow-auto transition-colors"
              style={{
                color: DARK_THEME.textPrimary,
                background: DARK_THEME.bgMain,
              }}
              onClick={() => copyToClipboard(subagent.output)}
              title="Click to copy output"
              onMouseEnter={(e) => e.currentTarget.style.background = DARK_THEME.bgHover}
              onMouseLeave={(e) => e.currentTarget.style.background = DARK_THEME.bgMain}
            >
              {outputExpanded || !isLongOutput ? (
                <pre className="whitespace-pre-wrap break-all">{subagent.output}</pre>
              ) : (
                <span>{subagent.output.slice(0, 300)}...</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}