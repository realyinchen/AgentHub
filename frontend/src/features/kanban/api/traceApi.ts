/** API client for Agent Trace Kanban Viewer. */

import { getCurrentUserId } from "@/lib/api"
import type { TraceListResponse, StepOutput, ExecutionDag } from '../types/trace';

const API_BASE = '/api/v1';

/**
 * Get user_id query parameter.
 * Throws error if no user is selected.
 */
function userIdQuery(): string {
  const id = getCurrentUserId()
  if (!id) throw new Error("No user selected. Please select a user first.")
  return `user_id=${encodeURIComponent(id)}`
}

/**
 * Fetch paginated trace list.
 * Backend API: GET /api/v1/traces
 * 
 * @param page - Page number (0-indexed)
 * @param pageSize - Number of items per page (1-100)
 * @param hours - Time filter in hours (1-168)
 */
export async function fetchTraces(
  page = 0,
  pageSize = 10,
  hours = 24
): Promise<TraceListResponse> {
  const res = await fetch(
    `${API_BASE}/traces?${userIdQuery()}&page=${page}&page_size=${pageSize}&hours=${hours}`
  );
  if (!res.ok) throw new Error(`Failed to fetch traces: ${res.statusText}`);
  return res.json();
}

/**
 * Fetch execution steps for a specific trace/thread.
 * Backend API: GET /api/v1/traces/{thread_id}/steps
 * 
 * @param threadId - The thread/conversation ID
 */
export async function fetchTraceSteps(threadId: string): Promise<StepOutput[]> {
  const res = await fetch(
    `${API_BASE}/traces/${encodeURIComponent(threadId)}/steps?${userIdQuery()}`
  );
  if (!res.ok) throw new Error(`Failed to fetch trace steps: ${res.statusText}`);
  return res.json();
}

/**
 * Fetch execution DAG for a specific trace/thread.
 * Backend API: GET /api/v1/traces/{thread_id}/dag
 * 
 * @param threadId - The thread/conversation ID
 */
export async function fetchTraceDag(threadId: string): Promise<ExecutionDag> {
  const res = await fetch(
    `${API_BASE}/traces/${encodeURIComponent(threadId)}/dag?${userIdQuery()}`
  );
  if (!res.ok) throw new Error(`Failed to fetch trace DAG: ${res.statusText}`);
  return res.json();
}

/**
 * Fetch a specific step by step number.
 * Backend API: GET /api/v1/traces/{thread_id}/steps/{step_number}
 * 
 * @param threadId - The thread/conversation ID
 * @param stepNumber - The step number (1-indexed)
 */
export async function fetchTraceStep(
  threadId: string,
  stepNumber: number
): Promise<StepOutput> {
  const res = await fetch(
    `${API_BASE}/traces/${encodeURIComponent(threadId)}/steps/${stepNumber}?${userIdQuery()}`
  );
  if (!res.ok) throw new Error(`Failed to fetch trace step: ${res.statusText}`);
  return res.json();
}

/**
 * Fetch a specific step by checkpoint ID.
 * Backend API: GET /api/v1/traces/{thread_id}/checkpoints/{checkpoint_id}
 * 
 * @param threadId - The thread/conversation ID
 * @param checkpointId - The checkpoint ID
 */
export async function fetchTraceCheckpoint(
  threadId: string,
  checkpointId: string
): Promise<StepOutput> {
  const res = await fetch(
    `${API_BASE}/traces/${encodeURIComponent(threadId)}/checkpoints/${encodeURIComponent(checkpointId)}?${userIdQuery()}`
  );
  if (!res.ok) throw new Error(`Failed to fetch trace checkpoint: ${res.statusText}`);
  return res.json();
}

/**
 * Replay a range of execution steps.
 * Backend API: GET /api/v1/traces/{thread_id}/replay
 * 
 * @param threadId - The thread/conversation ID
 * @param fromStep - Starting step number (>=1)
 * @param toStep - Ending step number (optional)
 */
export async function replayTrace(
  threadId: string,
  fromStep = 1,
  toStep?: number
): Promise<StepOutput[]> {
  let url = `${API_BASE}/traces/${encodeURIComponent(threadId)}/replay?${userIdQuery()}&from_step=${fromStep}`;
  if (toStep !== undefined) {
    url += `&to_step=${toStep}`;
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to replay trace: ${res.statusText}`);
  return res.json();
}