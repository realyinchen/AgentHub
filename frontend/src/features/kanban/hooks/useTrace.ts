/**
 * React hooks for Agent Trace Kanban Viewer.
 * Follows the same pattern as use-models.ts.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchTraces, fetchTrace } from '../api/traceApi';
import type { TraceListItem, AgentTrace } from '../types/trace';

// ============================================================================
// useTraceList - Hook for trace list page
// ============================================================================

/**
 * Hook to fetch and manage the trace list.
 *
 * @param limit - Number of traces to fetch (default: 20)
 * @returns An object containing:
 *   - traces: TraceListItem[] - List of traces
 *   - isLoading: boolean - Loading state
 *   - error: string | null - Error message if fetch failed
 *   - refresh: () => Promise<void> - Refresh the trace list
 */
export function useTraceList(limit = 20) {
  const [traces, setTraces] = useState<TraceListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Track if component is mounted to prevent state updates after unmount
  const mountedRef = useRef(true);

  // Unified fetch function with mounted check
  const fetchTraceList = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await fetchTraces(0, limit);
      if (mountedRef.current) {
        setTraces(result.items);
        setError(null);
      }
    } catch (err) {
      console.error('Failed to fetch traces:', err);
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to fetch traces');
      }
    } finally {
      if (mountedRef.current) {
        setIsLoading(false);
      }
    }
  }, [limit]);

  // Fetch on mount
  useEffect(() => {
    mountedRef.current = true;
    fetchTraceList();

    return () => {
      mountedRef.current = false;
    };
  }, [fetchTraceList]);

  return {
    traces,
    isLoading,
    error,
    refresh: fetchTraceList,
  };
}

// ============================================================================
// useTraceDetail - Hook for trace detail page
// ============================================================================

/**
 * Hook to fetch a single trace detail.
 *
 * @param threadId - The trace thread ID
 * @returns An object containing:
 *   - trace: AgentTrace | null - The full trace data
 *   - isLoading: boolean - Loading state
 *   - error: string | null - Error message if fetch failed
 *   - refresh: () => Promise<void> - Refresh the trace
 */
export function useTraceDetail(threadId: string | undefined) {
  const [trace, setTrace] = useState<AgentTrace | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Track if component is mounted
  const mountedRef = useRef(true);

  // Fetch trace detail
  const fetchTraceDetail = useCallback(async () => {
    if (!threadId) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    try {
      const result = await fetchTrace(threadId);
      if (mountedRef.current) {
        setTrace(result);
        setError(null);
      }
    } catch (err) {
      console.error('Failed to fetch trace:', err);
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to fetch trace');
      }
    } finally {
      if (mountedRef.current) {
        setIsLoading(false);
      }
    }
  }, [threadId]);

  // Fetch on mount and when threadId changes
  useEffect(() => {
    mountedRef.current = true;
    fetchTraceDetail();

    return () => {
      mountedRef.current = false;
    };
  }, [fetchTraceDetail]);

  return {
    trace,
    isLoading,
    error,
    refresh: fetchTraceDetail,
  };
}