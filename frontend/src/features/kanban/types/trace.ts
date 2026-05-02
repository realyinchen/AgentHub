/**
 * TypeScript interfaces for Agent Trace Kanban Viewer.
 * Precisely aligned with backend schemas/trace.py.
 */

// ============================================================================
// Base models
// ============================================================================

/** A tool call issued by the AI. */
export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  id?: string;  // Optional tool call ID for matching results
}

/** Tool execution result. */
export interface ToolResultInfo {
  tool_call_id?: string;  // Corresponding tool_call ID
  name: string;
  args: Record<string, unknown>;
  output: string;
  latency_ms?: number;
  status: "success" | "error";
}

/** AI message details. */
export interface AIMessageInfo {
  content?: string;
  thinking?: string;
  tool_calls?: ToolCall[];
  model_name?: string;
  latency_ms?: number;
}

/** Subagent execution (black-box view). */
export interface SubagentRun {
  name: string;
  input: string;
  output: string;
  latency_ms: number;
  step_count: number;
}

// ============================================================================
// Agent Turn - Kanban core unit
// ============================================================================

/**
 * Represents a complete agent execution turn.
 * 
 * Kanban card structure:
 * ┌─────────────────────────────────┐
 * │ Human Message                   │  ← humanMsg (blue)
 * ├─────────────────────────────────┤
 * │ AI Message                      │  ← aiMsg (purple)
 * │   └─ Thinking                   │
 * │   └─ Tool Calls                 │
 * ├─────────────────────────────────┤
 * │ [Parallel] Tool Results         │  ← toolMsgs (cyan/orange)
 * ├─────────────────────────────────┤
 * │ [Subagent: name]                │  ← subagentRuns (light purple)
 * ├─────────────────────────────────┤
 * │ AI Final Response               │  ← aiFinalResponse (green)
 * └─────────────────────────────────┘
 */
export interface AgentTurn {
  turn_id: string;
  session_id?: string | null;
  humanMsg: string;
  aiMsg?: AIMessageInfo;  // Optional, has default_factory on backend
  toolMsgs: ToolResultInfo[];
  subagentRuns: SubagentRun[];
  isParallelTools: boolean;
  aiFinalResponse?: AIMessageInfo;
  total_latency_ms: number;
  started_at: string;  // ISO date string
}

// ============================================================================
// Agent Trace - complete conversation trace
// ============================================================================

/** Trace list item (for trace list view). */
export interface TraceListItem {
  thread_id: string;  // UUID as string
  title: string;
  total_turns: number;
  total_latency_ms: number;
  last_updated: string;  // ISO date string
}

/** Response wrapper for trace list with pagination metadata. */
export interface TraceListResponse {
  items: TraceListItem[];
  total: number;
  total_pages: number;
  page: number;
  page_size: number;
  has_more: boolean;
  filter_hours: number;
}

/** Agent complete execution trace (data source for Kanban view). */
export interface AgentTrace {
  thread_id: string;  // UUID as string
  title: string;
  turns: AgentTurn[];
  total_turns: number;
  total_tool_calls: number;
  total_subagent_calls: number;
  total_latency_ms: number;
  generated_at: string;  // ISO date string
}

// ============================================================================
// Color Constants (for visual association)
// ============================================================================

/**
 * Color palette for tool call/result visual association.
 * Each pair gets a unique color from this palette.
 */
export const TOOL_COLOR_PALETTE = [
  '#f59e0b',  // amber-500
  '#3b82f6',  // blue-500
  '#10b981',  // emerald-500
  '#8b5cf6',  // violet-500
  '#ec4899',  // pink-500
  '#06b6d4',  // cyan-500
  '#84cc16',  // lime-500
  '#f97316',  // orange-500
];

/** Get a color from the palette by index. */
export function getToolColor(index: number): string {
  return TOOL_COLOR_PALETTE[index % TOOL_COLOR_PALETTE.length];
}