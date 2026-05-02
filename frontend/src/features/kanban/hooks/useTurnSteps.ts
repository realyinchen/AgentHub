/**
 * Hook to fetch raw message steps for a specific turn (session).
 * Used by the DAG visualization to render execution flow.
 */

import { useState, useEffect } from 'react';
import type { MessageStepRaw } from '../types/dag';

interface UseTurnStepsResult {
  steps: MessageStepRaw[];
  loading: boolean;
  error: string | null;
}

export function useTurnSteps(threadId: string | undefined, sessionId: string | undefined): UseTurnStepsResult {
  const [steps, setSteps] = useState<MessageStepRaw[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!threadId || !sessionId) {
      setSteps([]);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(`/api/v1/traces/${threadId}/turns/${sessionId}/steps`)
      .then(res => {
        if (!res.ok) throw new Error(`Failed to fetch turn steps: ${res.status}`);
        return res.json();
      })
      .then((data: MessageStepRaw[]) => {
        if (!cancelled) {
          setSteps(data);
        }
      })
      .catch(err => {
        if (!cancelled) {
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
  }, [threadId, sessionId]);

  return { steps, loading, error };
}