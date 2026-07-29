import type { DAGNodeType } from '../types/dag';

const HUMAN_NODE_WIDTH = 80;
const AI_NODE_WIDTH = 80;
const AI_THINKING_NODE_WIDTH = 112;
const TOOL_NODE_MIN_WIDTH = 100;
const NODE_HEIGHT = 44;
const AI_THINKING_NODE_HEIGHT = 58;
const TOOL_NODE_HEIGHT = 58;
const CHAR_WIDTH_APPROX = 8;
const PADDING_X = 40;

export interface NodeMetricInput {
  toolName?: string;
  thinking?: string | null;
  thinkingStatus?: string | null;
}

export function measureDAGNode(
  type: Extract<DAGNodeType, 'human' | 'ai' | 'tool'>,
  data: NodeMetricInput,
): { width: number; height: number } {
  if (type === 'human') {
    return { width: HUMAN_NODE_WIDTH, height: NODE_HEIGHT };
  }
  if (type === 'ai') {
    if (data.thinking?.trim() || data.thinkingStatus) {
      return {
        width: AI_THINKING_NODE_WIDTH,
        height: AI_THINKING_NODE_HEIGHT,
      };
    }
    return { width: AI_NODE_WIDTH, height: NODE_HEIGHT };
  }
  const width = Math.max(
    TOOL_NODE_MIN_WIDTH,
    (data.toolName?.length || 8) * CHAR_WIDTH_APPROX + PADDING_X,
  );
  return { width, height: TOOL_NODE_HEIGHT };
}
