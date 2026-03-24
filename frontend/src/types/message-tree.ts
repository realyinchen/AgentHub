/**
 * Message Node for tree-structured conversation history.
 * This is the core data structure for Grok-style branching chat.
 */
export interface MessageNode {
  id: string;
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  parent_id: string | null;
  branch_index: number;
  created_at: string;
  tool_calls: Array<{
    name: string;
    id: string;
    args: Record<string, unknown>;
    output?: string;
    order?: number;
  }> | null;
  tool_call_status: "pending" | "completed" | "failed" | null;
  custom_data: Record<string, unknown> | null;
  children_ids: string[];
}

/**
 * Complete message tree for a conversation.
 */
export interface MessageTree {
  nodes: MessageNode[];
  root_id: string | null;
  current_leaf_id: string | null;
}

/**
 * Create payload for a new message node.
 */
export interface MessageNodeCreate {
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  parent_id: string | null;
  branch_index?: number;
  tool_calls?: Array<{
    name: string;
    id: string;
    args: Record<string, unknown>;
    output?: string;
    order?: number;
  }> | null;
  tool_call_status?: "pending" | "completed" | "failed" | null;
  custom_data?: Record<string, unknown> | null;
}

/**
 * Update payload for a message node.
 */
export interface MessageNodeUpdate {
  content?: string;
  tool_calls?: Array<{
    name: string;
    id: string;
    args: Record<string, unknown>;
    output?: string;
    order?: number;
  }> | null;
  tool_call_status?: "pending" | "completed" | "failed" | null;
  custom_data?: Record<string, unknown> | null;
}

/**
 * Current leaf update payload.
 */
export interface CurrentLeafUpdate {
  current_leaf_id: string;
}

/**
 * Branch info for a message node (for branch selector UI).
 */
export interface BranchInfo {
  node_id: string;
  branch_index: number;
  total_siblings: number;
  is_current: boolean;
  preview?: string; // First 50 chars of content for preview
}
