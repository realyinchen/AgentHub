/**
 * useDAGFlow - Converts MessageStepRaw[] to React Flow nodes and edges.
 * Theme-aware via CSS custom properties — follows light/dark mode.
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
// Color palette (theme-aware via CSS custom properties)
// Maps FlowNodeType to CSS variable references for each visual property.
// These resolve differently under :root (light) vs .dark (dark) themes.
// ============================================================================

export const NODE_COLORS: Record<FlowNodeType, {
  primary: string;
  glow: string;
  border: string;
  bg: string;
}> = {
  'user': {
    primary: 'var(--dag-node-human-border)',
    glow: 'var(--dag-node-human-glow)',
    border: 'var(--dag-node-human-border)',
    bg: 'var(--dag-node-human-bg)',
  },
  'tool': {
    primary: 'var(--dag-node-tool-border)',
    glow: 'var(--dag-node-tool-glow)',
    border: 'var(--dag-node-tool-border)',
    bg: 'var(--dag-node-tool-bg)',
  },
  'middle-ai': {
    primary: 'var(--dag-node-ai-border)',
    glow: 'var(--dag-node-ai-glow)',
    border: 'var(--dag-node-ai-border)',
    bg: 'var(--dag-node-ai-bg)',
  },
  'final-ai': {
    primary: 'var(--dag-node-final-border)',
    glow: 'var(--dag-node-final-glow)',
    border: 'var(--dag-node-final-border)',
    bg: 'var(--dag-node-final-bg)',
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