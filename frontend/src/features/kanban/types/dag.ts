/**
 * Types for DAG visualization of agent execution steps.
 * Pure CSS implementation — no React Flow dependency.
 */

// ============================================================================
// Raw step from API (matches backend MessageStep schema)
// ============================================================================

export interface ToolCallRaw {
  name: string;
  args: Record<string, unknown>;
  id?: string;
}

export interface MessageStepRaw {
  session_id: string;
  step_number: number;
  message_type: 'human' | 'ai' | 'tool';
  content?: string | null;
  thinking?: string | null;
  thinking_status?: string | null;
  tool_calls?: ToolCallRaw[] | null;
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  tool_output?: string | null;
  tool_call_id?: string | null;
  model_name?: string | null;
  latency_ms?: number | null;
  system_executed?: boolean;
  tool_status?: string | null;
  tool_error?: string | null;
  action_id?: string | null;
  depends_on?: string[];
}

export interface ExecutionGraphNodeRaw {
  node_id: string;
  kind: 'user' | 'action' | 'response';
  label: string;
  status: string;
  order: number;
  step_number: number;
  action_id?: string | null;
  capability?: string | null;
  operation?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ExecutionGraphEdgeRaw {
  edge_id: string;
  source_id: string;
  target_id: string;
  relation: 'dependency' | 'entry' | 'response';
}

export interface ExecutionGraphRaw {
  contract_version: 'execution-graph-v2' | string;
  plan_id: string;
  request_id: string;
  entry_node_id: string;
  exit_node_id: string;
  nodes: ExecutionGraphNodeRaw[];
  edges: ExecutionGraphEdgeRaw[];
}

export interface LegacyDagNodeRaw {
  node_id: string;
  step_number: number;
  node_name: string;
  title: string;
  message_type: 'human' | 'ai' | 'tool';
  step: MessageStepRaw;
}

export interface ExecutionDagRaw {
  thread_id: string;
  nodes: LegacyDagNodeRaw[];
  edges: Array<[string, string]>;
  total_steps: number;
  steps: MessageStepRaw[];
  execution_graph?: ExecutionGraphRaw | null;
}

// ============================================================================
// Node types for pure CSS DAG
// ============================================================================

export type DAGNodeType = 'human' | 'ai' | 'tool' | 'subagent';

export interface BaseNodeData {
  type: DAGNodeType;
  stepNumber: number;
}

export interface HumanNodeData extends BaseNodeData {
  type: 'human';
  content: string;
}

export interface AINodeData extends BaseNodeData {
  type: 'ai';
  thinking?: string | null;
  thinkingStatus?: string | null;
  toolCalls?: ToolCallRaw[] | null;
  content?: string | null;
  modelName?: string | null;
  isFinal: boolean;
}

export interface ToolNodeData extends BaseNodeData {
  type: 'tool';
  toolName: string;
  toolArgs: Record<string, unknown> | null;
  toolOutput: string | null;
  toolStatus?: string | null;
  toolError?: string | null;
  index: number;
}

export interface SubAgentNodeData extends BaseNodeData {
  type: 'subagent';
  agentName: string;
  modelName?: string | null;
}

export type DAGNodeData =
  | HumanNodeData
  | AINodeData
  | ToolNodeData
  | SubAgentNodeData;

// ============================================================================
// Layout node (with position for rendering)
// ============================================================================

export interface LayoutNode {
  id: string;
  data: DAGNodeData;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface LayoutEdge {
  id: string;
  sourceId: string;
  targetId: string;
  relation?: string;
}

export interface LayoutBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

// ============================================================================
// DAG build result
// ============================================================================

export interface DAGResult {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  bounds: LayoutBounds;
  summary: {
    totalToolCalls: number;
    totalSteps: number;
    hasThinking: boolean;
    modelName?: string | null;
  };
}
