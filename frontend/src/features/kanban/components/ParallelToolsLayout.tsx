/**
 * ParallelToolsLayout - Displays tool calls and results in a grid layout
 * with visual association between matching pairs.
 * Style: Flat, solid borders, no glow
 */

import { useMemo } from 'react';
import { Zap } from 'lucide-react';
import type { ToolCall, ToolResultInfo } from '../types/trace';
import { getToolColor } from '../types/trace';
import { formatLatency } from '../utils/traceUtils';
import { ToolCallCard } from './ToolCallCard';
import { ToolResultCard } from './ToolResultCard';
import { DARK_THEME } from '../styles/theme';

interface ParallelToolsLayoutProps {
  toolCalls: ToolCall[];
  toolResults: ToolResultInfo[];
  totalLatencyMs?: number;
}

interface ToolPair {
  toolCall: ToolCall;
  toolResult?: ToolResultInfo;
  color: string;
  index: number;
}

/**
 * ToolPairItem - A single tool call + result pair with visual connection
 */
interface ToolPairItemProps {
  toolCall: ToolCall;
  toolResult?: ToolResultInfo;
  color: string;
  index: number;
}

function ToolPairItem({ toolCall, toolResult, color, index }: ToolPairItemProps) {
  return (
    <div key={toolCall.id || `pair-${index}`} className="space-y-2">
      {/* Connection header - flat style */}
      <div className="flex items-center gap-2">
        <div
          className="w-full h-[1px]"
          style={{ background: DARK_THEME.border }}
        />
        <span
          className="text-[10px] font-mono whitespace-nowrap px-1.5 py-0.5 rounded"
          style={{
            background: DARK_THEME.bgPanel,
            color: DARK_THEME.textSecondary,
            border: `1px solid ${DARK_THEME.border}`,
          }}
        >
          #{index + 1}
        </span>
        <div
          className="w-full h-[1px]"
          style={{ background: DARK_THEME.border }}
        />
      </div>

      {/* Tool Call Card with color border */}
      <ToolCallCard
        toolCall={toolCall}
        associationColor={color}
        showIndex={index}
      />

      {/* Tool Result Card with color border (if exists) */}
      {toolResult && (
        <ToolResultCard
          toolResult={toolResult}
          associationColor={color}
          showIndex={index}
        />
      )}
    </div>
  );
}

export function ParallelToolsLayout({
  toolCalls,
  toolResults,
  totalLatencyMs,
}: ParallelToolsLayoutProps) {
  // Match tool calls with results and assign colors
  const toolPairs = useMemo<ToolPair[]>(() => {
    // Create a map of tool_call_id -> result
    const resultMap = new Map<string, ToolResultInfo>();
    for (const result of toolResults) {
      if (result.tool_call_id) {
        resultMap.set(result.tool_call_id, result);
      }
    }

    // Pair each call with its result (if exists)
    return toolCalls.map((call, index) => {
      const matchingResult = call.id ? resultMap.get(call.id) : undefined;
      return {
        toolCall: call,
        toolResult: matchingResult,
        color: getToolColor(index),
        index,
      };
    });
  }, [toolCalls, toolResults]);

  // Find unmatched results (results without a corresponding tool call)
  const unmatchedResults = useMemo(() => {
    const matchedIds = new Set(
      toolPairs
        .filter((p) => p.toolResult?.tool_call_id)
        .map((p) => p.toolResult!.tool_call_id!)
    );
    return toolResults.filter(
      (r) => !r.tool_call_id || !matchedIds.has(r.tool_call_id)
    );
  }, [toolPairs, toolResults]);

  return (
    <div className="space-y-3">
      {/* Parallel Execution Header - flat style */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <span
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold"
            style={{
              background: DARK_THEME.bgPanel,
              border: `1px solid ${DARK_THEME.border}`,
              color: DARK_THEME.nodeTool,
            }}
          >
            <Zap className="w-3 h-3" />
            Parallel Execution
          </span>
          {totalLatencyMs && (
            <span
              className="text-xs font-mono"
              style={{ color: DARK_THEME.textDim }}
            >
              {formatLatency(totalLatencyMs)} total
            </span>
          )}
        </div>
        <span
          className="text-xs"
          style={{ color: DARK_THEME.textDim }}
        >
          {toolCalls.length} tool{toolCalls.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Grid Layout - 2 columns on desktop, 1 column on mobile */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {toolPairs.map(({ toolCall, toolResult, color, index }) => (
          <ToolPairItem
            key={toolCall.id || `pair-${index}`}
            toolCall={toolCall}
            toolResult={toolResult}
            color={color}
            index={index}
          />
        ))}
      </div>

      {/* Unmatched results - same grid style without header */}
      {unmatchedResults.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mt-3">
          {unmatchedResults.map((result, idx) => (
            <ToolResultCard
              key={result.tool_call_id || `unmatched-${idx}`}
              toolResult={result}
            />
          ))}
        </div>
      )}
    </div>
  );
}