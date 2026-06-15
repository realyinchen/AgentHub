/**
 * useDAGFlow - Converts MessageStepRaw[] to React Flow nodes and edges.
 * Fixed dark cyberpunk theme — all colors hardcoded, no CSS variable dependencies.
 */

import { useMemo } from 'react';
import { Position, type Node, type Edge } from '@xyflow/react';
import type { MessageStepRaw, LayoutNode } from '../../../types/dag';
import { buildDAGFromSteps } from '../../../utils/dagBuilder';

// ============================================================================
// Node type constants
// ============================================================================

export type FlowNodeType = 'user' | 'tool' | 'middle-ai' | 'final-ai';

export interface FlowNodeData extends Record<string, unknown> {
  type: FlowNodeType;
  label: string;
  subtitle: string;
  stepNumber: number;
  /** Raw data for detail sheet */
  rawData: LayoutNode['data'];
}

// ============================================================================
// Color palette (hardcoded — does NOT follow system theme)
// ============================================================================

export const NODE_COLORS: Record<FlowNodeType, {
  primary: string;
  glow: string;
  border: string;
  bg: string;
}> = {
  'user': {
    primary: '#3B82F6',
    glow: 'rgba(59, 130, 246, 0.4)',
    border: 'rgba(59, 130, 246, 0.6)',
    bg: 'rgba(59, 130, 246, 0.08)',
  },
  'tool': {
    primary: '#8B5CF6',
    glow: 'rgba(139, 92, 246, 0.4)',
    border: 'rgba(139, 92, 246, 0.6)',
    bg: 'rgba(139, 92, 246, 0.08)',
  },
  'middle-ai': {
    primary: '#F59E0B',
    glow: 'rgba(245, 158, 11, 0.4)',
    border: 'rgba(245, 158, 11, 0.6)',
    bg: 'rgba(245, 158, 11, 0.08)',
  },
  'final-ai': {
    primary: '#10B981',
    glow: 'rgba(16, 185, 129, 0.4)',
    border: 'rgba(16, 185, 129, 0.6)',
    bg: 'rgba(16, 185, 129, 0.08)',
  },
};

// ============================================================================
// Determine FlowNodeType from LayoutNode data
// ============================================================================

function getFlowNodeType(data: LayoutNode['data']): FlowNodeType {
  switch (data.type) {
    case 'human':
      return 'user';
    case 'tool':
      return 'tool';
    case 'ai':
      return data.isFinal ? 'final-ai' : 'middle-ai';
    case 'subagent':
      return 'middle-ai'; // subagent treated as middle AI
    default:
      return 'middle-ai';
  }
}

function getNodeLabel(data: LayoutNode['data']): string {
  switch (data.type) {
    case 'human':
      return 'User';
    case 'tool':
      return data.toolName;
    case 'ai':
      return 'AI';
    case 'subagent':
      return data.agentName;
    default:
      return 'Node';
  }
}

function getNodeSubtitle(data: LayoutNode['data']): string {
  switch (data.type) {
    case 'human':
      return `Step ${data.stepNumber}`;
    case 'tool':
      return 'Tool';
    case 'ai':
      return data.isFinal ? 'Final' : 'Processing';
    case 'subagent':
      return 'SubAgent';
    default:
      return '';
  }
}

// ============================================================================
// Hook
// ============================================================================

export interface DAGFlowResult {
  nodes: Node<FlowNodeData>[];
  edges: Edge[];
  summary: {
    totalToolCalls: number;
    totalSteps: number;
    hasThinking: boolean;
    modelName?: string | null;
  };
}

export function useDAGFlow(steps: MessageStepRaw[]): DAGFlowResult {
  return useMemo(() => {
    const dagResult = buildDAGFromSteps(steps);
    const { nodes: layoutNodes, edges: layoutEdges, summary } = dagResult;

    // Calculate bounding box for centering
    let minX = Infinity, minY = Infinity;
    for (const n of layoutNodes) {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
    }
    const offsetX = -minX + 80;
    const offsetY = -minY + 80;

    // Convert layout nodes to React Flow nodes
    const flowNodes: Node<FlowNodeData>[] = layoutNodes.map((ln) => {
      const flowType = getFlowNodeType(ln.data);
      return {
        id: ln.id,
        type: flowType,
        position: {
          x: ln.x + offsetX,
          y: ln.y + offsetY,
        },
        data: {
          type: flowType,
          label: getNodeLabel(ln.data),
          subtitle: getNodeSubtitle(ln.data),
          stepNumber: ln.data.stepNumber,
          rawData: ln.data,
        },
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
        style: { width: 180, height: 56 },
      };
    });

    // Build node map for edge conversion
    const nodeMap = new Map(layoutNodes.map(n => [n.id, n]));

    // Convert layout edges to React Flow edges
    const flowEdges: Edge[] = layoutEdges.map((le) => {
      const sourceNode = nodeMap.get(le.sourceId);
      const targetNode = nodeMap.get(le.targetId);
      const sourceType = sourceNode ? getFlowNodeType(sourceNode.data) : 'middle-ai';
      const targetType = targetNode ? getFlowNodeType(targetNode.data) : 'middle-ai';

      return {
        id: le.id,
        source: le.sourceId,
        target: le.targetId,
        type: 'glow',
        data: {
          sourceColor: NODE_COLORS[sourceType].primary,
          targetColor: NODE_COLORS[targetType].primary,
        },
        animated: true,
      };
    });

    return { nodes: flowNodes, edges: flowEdges, summary };
  }, [steps]);
}