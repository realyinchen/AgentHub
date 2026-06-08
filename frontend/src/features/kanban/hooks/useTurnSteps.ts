/**
 * Hook to fetch raw message steps for a specific turn (session).
 * Used by the DAG visualization to render execution flow.
 * 
 * Updated to use backend API: GET /api/v1/traces/{thread_id}/steps
 * Authentication is handled via HTTP-only JWT cookie.
 *
 * IMPORTANT: Only fetches when NOT streaming to avoid multiple API calls.
 * The DAG data is only available after streaming ends and is persisted.
 *
 * DEBOUNCE: Added debounce logic to prevent duplicate calls when
 * isStreaming changes to false and sessionId changes shortly after.
 */

import { useState, useEffect, useRef } from 'react';
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
  // Track last fetched key to prevent duplicate requests
  const lastFetchedKeyRef = useRef<string>('');
  // Debounce timer
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!threadId) {
      setSteps([]);
      lastFetchedKeyRef.current = '';
      return;
    }

    // Don't fetch during streaming - only fetch after streaming ends
    // This prevents multiple API calls before data is fully persisted
    if (isStreaming) {
      wasStreamingRef.current = true;
      return;
    }

    // Generate a unique key for this request
    const requestKey = `${threadId}:${sessionId || 'all'}`;

    // Skip if already fetched this exact data (prevent duplicate calls)
    if (lastFetchedKeyRef.current === requestKey) {
      return;
    }

    // Clear any pending debounce timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    // Debounce: wait 100ms before fetching to avoid duplicate calls
    // when both isStreaming and sessionId change in quick succession
    debounceTimerRef.current = setTimeout(() => {
      // Double-check the key hasn't been fetched while we waited
      if (lastFetchedKeyRef.current === requestKey) {
        return;
      }

      let cancelled = false;
      setLoading(true);
      setError(null);

      // Use the correct backend API endpoint
      // Authentication via HTTP-only cookie
      fetch(`/api/v1/traces/${threadId}/steps`, {
        credentials: "include",
      })
        .then(res => {
          if (res.status === 401) {
            window.location.href = "/login";
            throw new Error("Unauthorized");
          }
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
            // Mark this request as fetched
            lastFetchedKeyRef.current = requestKey;
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
    }, 100);

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, [threadId, sessionId, isStreaming]);

  return { steps, loading, error };
}