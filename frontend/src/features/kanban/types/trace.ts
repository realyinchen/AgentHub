/**
 * TypeScript interfaces for Agent Trace Kanban Viewer.
 * Precisely aligned with backend schemas/trace.py.
 */

// ============================================================================
// AI Metadata - AI message details
// ============================================================================

/** Tool call information within AI metadata. */
export interface ToolCallInStep {
  name: string
  args: Record<string, unknown>
  id?: string
}

/** AI message metadata from backend. */
export interface AIMetadata {
  thinking?: string | null
  tool_calls?: ToolCallInStep[] | null
  model_name?: string | null
}

// ============================================================================
// Tool Metadata - Tool execution details
// ============================================================================

/** Tool execution metadata from backend. */
export interface ToolMetadata {
  name: string
  args: Record<string, unknown>
  output?: string | null
  latency_ms?: number | null
  status?: "success" | "error" | null
}

// ============================================================================
// Step Output - Single execution step
// ============================================================================

/**
 * Single step in the agent execution sequence.
 * Each message from the conversation is represented as a step.
 * 
 * message_type values:
 * - human: User message
 * - ai: AI response with content and optional thinking/tool_calls
 * - tool: Tool execution result
 */
export interface StepOutput {
  step_number: number
  message_type: "human" | "ai" | "tool"
  content: string | null
  timestamp: string  // ISO date string
  message_id: string
  checkpoint_id: string
  node_name: string  // e.g., "human", "model", "tools"
  ai_metadata: AIMetadata | null
  tool_metadata: ToolMetadata | null
}

// ============================================================================
// Trace List Item
// ============================================================================

/** Trace list item (for trace list view). */
export interface TraceListItem {
  thread_id: string  // UUID as string
  title: string
  total_steps: number
  total_latency_ms: number
  last_updated: string  // ISO date string
}

// ============================================================================
// Trace List Response - Paginated trace list
// ============================================================================

/** Response wrapper for trace list with pagination metadata. */
export interface TraceListResponse {
  items: TraceListItem[]
  total: number
  total_pages: number
  page: number
  page_size: number
  has_more: boolean
  filter_hours: number
}

// ============================================================================
// DAG Node
// ============================================================================

/** Node in the execution DAG. */
export interface DagNode {
  node_id: string
  step_number: number
  node_name: string
  title: string
  message_type: string
  step: StepOutput
}

// ============================================================================
// Execution DAG - For visualization
// ============================================================================

/** Execution DAG for trace visualization. */
export interface ExecutionDag {
  thread_id: string
  nodes: DagNode[]
  edges: [string, string][]  // Array of [source_node_id, target_node_id]
  total_steps: number
  steps: StepOutput[]
}

// ============================================================================
// Legacy Types (for backward compatibility with existing Kanban components)
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
// Agent Turn - Kanban core unit (legacy format)
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
// Agent Trace - complete conversation trace (legacy format)
// ============================================================================

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

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Convert StepOutput array to AgentTrace format for legacy Kanban view.
 * This is useful for components that still expect the old AgentTrace format.
 */
export function stepsToAgentTrace(
  steps: StepOutput[],
  threadId: string,
  title: string
): AgentTrace {
  // Group steps by session (each session is one turn)
  // For now, we'll create a simple mapping
  const turns: AgentTurn[] = []
  let currentTurn: AgentTurn | null = null
  
  for (const step of steps) {
    if (step.message_type === "human") {
      // Start a new turn
      if (currentTurn) {
        turns.push(currentTurn)
      }
      currentTurn = {
        turn_id: step.message_id,
        session_id: null,
        humanMsg: step.content || "",
        aiMsg: undefined,
        toolMsgs: [],
        subagentRuns: [],
        isParallelTools: false,
        aiFinalResponse: undefined,
        total_latency_ms: 0,
        started_at: step.timestamp,
      }
    } else if (currentTurn) {
      if (step.message_type === "ai") {
        const aiMeta = step.ai_metadata
        currentTurn.aiMsg = {
          content: step.content || undefined,
          thinking: aiMeta?.thinking || undefined,
          tool_calls: aiMeta?.tool_calls || undefined,
          model_name: aiMeta?.model_name || undefined,
        }
      } else if (step.message_type === "tool") {
        const toolMeta = step.tool_metadata
        if (toolMeta) {
          currentTurn.toolMsgs.push({
            tool_call_id: undefined,
            name: toolMeta.name,
            args: toolMeta.args,
            output: toolMeta.output || "",
            latency_ms: toolMeta.latency_ms || 0,
            status: toolMeta.status || "success",
          })
        }
      }
    }
  }
  
  if (currentTurn) {
    turns.push(currentTurn)
  }
  
  return {
    thread_id: threadId,
    title,
    turns,
    total_turns: turns.length,
    total_tool_calls: turns.reduce((sum, t) => sum + t.toolMsgs.length, 0),
    total_subagent_calls: turns.reduce((sum, t) => sum + t.subagentRuns.length, 0),
    total_latency_ms: 0,
    generated_at: new Date().toISOString(),
  }
}