/**
 * Hook to fetch raw message steps for a specific turn (session).
 * Used by the DAG visualization to render execution flow.
 * 
 * Updated to use backend API: GET /api/v1/traces/{thread_id}/steps
 * with user_id parameter.
 * 
 * Added isStreaming parameter to refetch when streaming ends.
 */

import { useState, useEffect, useRef } from 'react';
import { getCurrentUserId } from '@/lib/api';
import type { MessageStepRaw } from '../types/dag';

interface UseTurnStepsResult {
  steps: MessageStepRaw[];
  loading: boolean;
  error: string | null;
}

export function useTurnSteps(
  threadId: string | undefined,
  sessionId: string | undefined,
  isStreaming?: boolean
): UseTurnStepsResult {
  const [steps, setSteps] = useState<MessageStepRaw[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Track previous streaming state to detect when streaming ends
  const wasStreamingRef = useRef(isStreaming);

  useEffect(() => {
    if (!threadId) {
      setSteps([]);
      return;
    }

    const userId = getCurrentUserId();
    if (!userId) {
      setError('No user selected');
      return;
    }

    // Track previous streaming state to detect when streaming ends
    wasStreamingRef.current = isStreaming;

    let cancelled = false;
    setLoading(true);
    setError(null);

    // Use the correct backend API endpoint with user_id
    fetch(`/api/v1/traces/${threadId}/steps?user_id=${encodeURIComponent(userId)}`)
      .then(res => {
        if (!res.ok) throw new Error(`Failed to fetch turn steps: ${res.status}`);
        return res.json();
      })
      .then((data: MessageStepRaw[]) => {
        if (!cancelled) {
          // Empty array is valid - means no trace data yet (new conversation)
          // Filter by sessionId if provided
          const filteredSteps = sessionId 
            ? data.filter(step => step.session_id === sessionId)
            : data;
          setSteps(filteredSteps);
          // Clear any previous error when data is successfully fetched
          setError(null);
        }
      })
      .catch(err => {
        if (!cancelled) {
          // Don't show error for new conversations without trace data
          // The backend returns empty array now, so this shouldn't happen
          // But keep error handling for genuine network/auth errors
          setError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [threadId, sessionId, isStreaming]);

  return { steps, loading, error };
}