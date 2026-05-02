/** API client for Agent Trace Kanban Viewer. */

import type { AgentTrace, TraceListResponse } from '../types/trace';

const API_BASE = '/api/v1';

export async function fetchTraces(skip = 0, limit = 20): Promise<TraceListResponse> {
  const res = await fetch(`${API_BASE}/traces?skip=${skip}&limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to fetch traces: ${res.statusText}`);
  return res.json();
}

export async function fetchTrace(threadId: string): Promise<AgentTrace> {
  const res = await fetch(`${API_BASE}/traces/${threadId}`);
  if (!res.ok) throw new Error(`Failed to fetch trace: ${res.statusText}`);
  return res.json();
}

export async function createTrace(trace: AgentTrace): Promise<AgentTrace> {
  const res = await fetch(`${API_BASE}/traces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(trace),
  });
  if (!res.ok) throw new Error(`Failed to create trace: ${res.statusText}`);
  return res.json();
}
