/**
 * React hooks for Agent Trace Kanban Viewer.
 * Follows the same pattern as use-models.ts.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchTraces, fetchTraceSteps, fetchTraceDag } from '../api/traceApi';
import type { TraceListItem, StepOutput, ExecutionDag, AgentTrace } from '../types/trace';
import { stepsToAgentTrace } from '../types/trace';

// ============================================================================
// useTraceList - Hook for trace list page
// ============================================================================

/**
 * Hook to fetch and manage the trace list.
 *
 * @param pageSize - Number of traces per page (default: 10)
 * @param hours - Time filter in hours (default: 24)
 * @returns An object containing:
 *   - traces: TraceListItem[] - List of traces
 *   - total: number - Total number of traces
 *   - totalPages: number - Total pages
 *   - page: number - Current page
 *   - hasMore: boolean - Whether there are more pages
 *   - isLoading: boolean - Loading state
 *   - error: string | null - Error message if fetch failed
 *   - refresh: () => Promise<void> - Refresh the trace list
 *   - loadPage: (page: number) => Promise<void> - Load a specific page
 */
export function useTraceList(pageSize = 10, hours = 24) {
  const [traces, setTraces] = useState<TraceListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Track if component is mounted to prevent state updates after unmount
  const mountedRef = useRef(true);

  // Unified fetch function with mounted check
  const fetchTraceList = useCallback(async (targetPage = 0) => {
    setIsLoading(true);
    try {
      const result = await fetchTraces(targetPage, pageSize, hours);
      if (mountedRef.current) {
        setTraces(result.items);
        setTotal(result.total);
        setTotalPages(result.total_pages);
        setPage(result.page);
        setHasMore(result.has_more);
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
  }, [pageSize, hours]);

  // Fetch on mount
  useEffect(() => {
    mountedRef.current = true;
    fetchTraceList(0);

    return () => {
      mountedRef.current = false;
    };
  }, [fetchTraceList]);

  // Load a specific page
  const loadPage = useCallback(async (targetPage: number) => {
    await fetchTraceList(targetPage);
  }, [fetchTraceList]);

  return {
    traces,
    total,
    totalPages,
    page,
    hasMore,
    isLoading,
    error,
    refresh: () => fetchTraceList(page),
    loadPage,
  };
}

// ============================================================================
// useTraceDetail - Hook for trace detail page
// ============================================================================

/**
 * Hook to fetch a single trace detail (execution steps).
 *
 * @param threadId - The trace thread ID
 * @returns An object containing:
 *   - steps: StepOutput[] - The execution steps
 *   - trace: AgentTrace | null - Legacy format for backward compatibility
 *   - isLoading: boolean - Loading state
 *   - error: string | null - Error message if fetch failed
 *   - refresh: () => Promise<void> - Refresh the trace
 */
export function useTraceDetail(threadId: string | undefined) {
  const [steps, setSteps] = useState<StepOutput[]>([]);
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
      const result = await fetchTraceSteps(threadId);
      if (mountedRef.current) {
        setSteps(result);
        // Convert to legacy AgentTrace format for backward compatibility
        setTrace(stepsToAgentTrace(result, threadId, 'Trace'));
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
    steps,
    trace,
    isLoading,
    error,
    refresh: fetchTraceDetail,
  };
}

// ============================================================================
// useTraceDag - Hook for trace DAG visualization
// ============================================================================

/**
 * Hook to fetch execution DAG for visualization.
 *
 * @param threadId - The trace thread ID
 * @returns An object containing:
 *   - dag: ExecutionDag | null - The DAG data
 *   - isLoading: boolean - Loading state
 *   - error: string | null - Error message if fetch failed
 *   - refresh: () => Promise<void> - Refresh the DAG
 */
export function useTraceDag(threadId: string | undefined) {
  const [dag, setDag] = useState<ExecutionDag | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Track if component is mounted
  const mountedRef = useRef(true);

  // Fetch DAG
  const fetchDag = useCallback(async () => {
    if (!threadId) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    try {
      const result = await fetchTraceDag(threadId);
      if (mountedRef.current) {
        setDag(result);
        setError(null);
      }
    } catch (err) {
      console.error('Failed to fetch trace DAG:', err);
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to fetch trace DAG');
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
    fetchDag();

    return () => {
      mountedRef.current = false;
    };
  }, [fetchDag]);

  return {
    dag,
    isLoading,
    error,
    refresh: fetchDag,
  };
}