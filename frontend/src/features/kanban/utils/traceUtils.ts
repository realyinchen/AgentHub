/**
 * Utility functions for Trace Kanban viewer.
 */

/** Format latency in milliseconds to human-readable string. */
export function formatLatency(ms?: number): string {
  if (!ms) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Copy text to clipboard with error handling. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Try to parse JSON string, return original if invalid. */
export function tryFormatJson(content: string): string {
  try {
    const parsed = JSON.parse(content);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return content;
  }
}

/** Truncate long text with ellipsis. */
export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength) + '...';
}

/** Format ISO date string to local datetime (browser system timezone). */
export function formatDate(isoString: string): string {
  try {
    // Ensure ISO string is treated as UTC (add Z suffix if missing)
    const utcString = isoString.endsWith('Z') ? isoString : isoString + 'Z';
    const date = new Date(utcString);
    if (Number.isNaN(date.getTime())) {
      return isoString;
    }
    // Format using browser's system timezone
    return date.toLocaleString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return isoString;
  }
}

/**
 * Match tool calls with their results by tool_call_id.
 * Returns an array of pairs with matching color.
 */
export function matchToolCallsWithResults(
  toolCalls: Array<{ id?: string }>,
  toolResults: Array<{ tool_call_id?: string }>
): Array<{
  call: typeof toolCalls[0] | null;
  result: typeof toolResults[0] | null;
  isMatched: boolean;
}> {
  const resultMap = new Map<string, typeof toolResults[0]>();
  for (const result of toolResults) {
    if (result.tool_call_id) {
      resultMap.set(result.tool_call_id, result);
    }
  }

  const matchedIds = new Set<string>();
  const pairs: Array<{
    call: typeof toolCalls[0] | null;
    result: typeof toolResults[0] | null;
    isMatched: boolean;
  }> = [];

  // Process calls with matches
  for (const call of toolCalls) {
    const result = call.id ? resultMap.get(call.id) : undefined;
    if (result) {
      matchedIds.add(call.id!);
      pairs.push({ call, result, isMatched: true });
    } else {
      pairs.push({ call, result: null, isMatched: false });
    }
  }

  // Add unmatched results
  for (const result of toolResults) {
    if (!result.tool_call_id || !matchedIds.has(result.tool_call_id)) {
      pairs.push({ call: null, result, isMatched: false });
    }
  }

  return pairs;
}