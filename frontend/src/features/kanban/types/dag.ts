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
  tool_calls?: ToolCallRaw[] | null;
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  tool_output?: string | null;
  tool_call_id?: string | null;
  model_name?: string | null;
  latency_ms?: number | null;
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
}

// ============================================================================
// DAG build result
// ============================================================================

export interface DAGResult {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  summary: {
    totalToolCalls: number;
    totalSteps: number;
    hasThinking: boolean;
    modelName?: string | null;
  };
}