/**
 * DAG Builder - Converts message steps to layout nodes and edges.
 * Pure CSS implementation — no React Flow dependency.
 * 
 * Layout:
 *   Layer 0: Human
 *   Layer 1: AI (with tool_calls) 
 *   Layer 2: Tools (merged call+result, parallel)
 *   ...repeat for multi-round...
 *   Layer N: Final AI Response
 */

import type { LayoutNode, LayoutEdge, DAGResult, MessageStepRaw } from '../types/dag';

const LAYER_GAP_Y = 140;  // Vertical gap between layers
const PARALLEL_GAP = 200; // Horizontal gap for parallel tools
const NODE_WIDTH = 140;
const NODE_HEIGHT = 60;

/**
 * Build DAG from message steps.
 */
export function buildDAGFromSteps(steps: MessageStepRaw[]): DAGResult {
  const sortedSteps = [...steps].sort((a, b) => a.step_number - b.step_number);

  if (sortedSteps.length === 0) {
    return { nodes: [], edges: [], summary: { totalToolCalls: 0, totalSteps: 0, hasThinking: false } };
  }

  // Pass 1: Group steps into layers
  const layers: LayerInfo[] = buildLayers(sortedSteps);

  // Pass 2: Create nodes with positions
  const { nodes } = createNodes(layers, sortedSteps);

  // Pass 3: Create edges
  const edges = createEdges(layers, nodes);

  // Build summary
  let totalToolCalls = 0;
  let hasThinking = false;
  let modelName: string | null = null;
  for (const step of sortedSteps) {
    if (step.message_type === 'ai') {
      if (step.tool_calls) totalToolCalls += step.tool_calls.length;
      if (step.thinking) hasThinking = true;
      if (step.model_name && !modelName) modelName = step.model_name;
    }
  }

  return {
    nodes,
    edges,
    summary: { totalToolCalls, totalSteps: sortedSteps.length, hasThinking, modelName },
  };
}

// ============================================================================
// Layer abstraction
// ============================================================================

interface LayerInfo {
  type: 'human' | 'ai' | 'tools';
  stepNumbers: number[];
  // For 'tools' layer: merged tool info (call + result paired)
  toolInfos?: ToolInfo[];
}

interface ToolInfo {
  toolName: string;
  toolArgs: Record<string, unknown> | null;
  toolOutput: string | null;
  toolCallId?: string;
}

function buildLayers(steps: MessageStepRaw[]): LayerInfo[] {
  const layers: LayerInfo[] = [];
  let i = 0;

  while (i < steps.length) {
    const step = steps[i];

    if (step.message_type === 'human') {
      layers.push({ type: 'human', stepNumbers: [step.step_number] });
      i++;
    }
    else if (step.message_type === 'ai' && step.tool_calls && step.tool_calls.length > 0) {
      // AI with tool calls
      layers.push({ type: 'ai', stepNumbers: [step.step_number] });
      i++;

      // Collect following tool results and pair with tool calls
      const toolInfos: ToolInfo[] = [];

      // Collect tool result steps
      const resultSteps: MessageStepRaw[] = [];
      while (i < steps.length && steps[i].message_type === 'tool') {
        resultSteps.push(steps[i]);
        i++;
      }

      // For each tool call, find its matching result (by tool_call_id)
      for (const tc of step.tool_calls) {
        const matchingResult = resultSteps.find(
          r => r.tool_call_id && tc.id && r.tool_call_id === tc.id
        );
        toolInfos.push({
          toolName: tc.name,
          toolArgs: tc.args && Object.keys(tc.args).length > 0 ? tc.args : null,
          toolOutput: matchingResult?.tool_output || null,
          toolCallId: tc.id,
        });
      }

      // If there are orphan results (no matching call), add them too
      const matchedResultIds = new Set(
        toolInfos.filter(t => t.toolCallId).map(t => t.toolCallId)
      );
      for (const r of resultSteps) {
        if (r.tool_call_id && !matchedResultIds.has(r.tool_call_id)) {
          toolInfos.push({
            toolName: r.tool_name || 'unknown',
            toolArgs: r.tool_args || null,
            toolOutput: r.tool_output || null,
          });
        }
      }

      layers.push({
        type: 'tools',
        stepNumbers: resultSteps.map(r => r.step_number),
        toolInfos,
      });
    }
    else if (step.message_type === 'ai') {
      // AI without tool calls (final or simple)
      layers.push({ type: 'ai', stepNumbers: [step.step_number] });
      i++;
    }
    else if (step.message_type === 'tool') {
      // Orphan tool result (shouldn't happen normally)
      layers.push({
        type: 'tools',
        stepNumbers: [step.step_number],
        toolInfos: [{
          toolName: step.tool_name || 'unknown',
          toolArgs: step.tool_args || null,
          toolOutput: step.tool_output || null,
        }],
      });
      i++;
    }
    else {
      i++;
    }
  }

  return layers;
}

// ============================================================================
// Node creation
// ============================================================================

function createNodes(layers: LayerInfo[], steps: MessageStepRaw[]): { nodes: LayoutNode[] } {
  const nodes: LayoutNode[] = [];
  let currentY = 0;
  let toolIndex = 0;

  const stepMap = new Map(steps.map(s => [s.step_number, s]));

  for (const layer of layers) {
    if (layer.type === 'human') {
      const step = stepMap.get(layer.stepNumbers[0])!;
      const nodeId = `human-${step.step_number}`;
      nodes.push({
        id: nodeId,
        data: { type: 'human', content: step.content || '', stepNumber: step.step_number },
        x: 0,
        y: currentY,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
      });
      currentY += LAYER_GAP_Y;
    }
    else if (layer.type === 'ai') {
      const step = stepMap.get(layer.stepNumbers[0])!;
      const isFinal = !step.tool_calls || step.tool_calls.length === 0;
      const nodeId = `ai-${step.step_number}`;
      nodes.push({
        id: nodeId,
        data: {
          type: 'ai',
          thinking: step.thinking,
          toolCalls: step.tool_calls ?? undefined,
          content: step.content,
          modelName: step.model_name,
          stepNumber: step.step_number,
          isFinal,
        },
        x: 0,
        y: currentY,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
      });
      currentY += LAYER_GAP_Y;
    }
    else if (layer.type === 'tools' && layer.toolInfos) {
      const count = layer.toolInfos.length;
      const startX = -((count - 1) * PARALLEL_GAP) / 2;

      layer.toolInfos.forEach((toolInfo, idx) => {
        const stepNum = layer.stepNumbers[idx] ?? layer.stepNumbers[0];
        const nodeId = `tool-${stepNum}-${idx}`;
        nodes.push({
          id: nodeId,
          data: {
            type: 'tool',
            toolName: toolInfo.toolName,
            toolArgs: toolInfo.toolArgs,
            toolOutput: toolInfo.toolOutput,
            index: toolIndex,
            stepNumber: stepNum,
          },
          x: startX + idx * PARALLEL_GAP,
          y: currentY,
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
        });
        toolIndex++;
      });
      currentY += LAYER_GAP_Y;
    }
  }

  return { nodes };
}

// ============================================================================
// Edge creation
// ============================================================================

function createEdges(layers: LayerInfo[], nodes: LayoutNode[]): LayoutEdge[] {
  const edges: LayoutEdge[] = [];

  function findNodeId(type: string, stepNumber: number): string | undefined {
    return nodes.find(n => n.data.type === type && n.data.stepNumber === stepNumber)?.id;
  }

  function findToolNodeId(layerIndex: number, toolIndex: number): string | undefined {
    const layer = layers[layerIndex];
    if (!layer || layer.type !== 'tools' || !layer.toolInfos) return undefined;
    const stepNum = layer.stepNumbers[toolIndex] ?? layer.stepNumbers[0];
    return nodes.find(n => n.id === `tool-${stepNum}-${toolIndex}`)?.id;
  }

  function addEdge(sourceId: string, targetId: string) {
    const edgeId = `edge-${sourceId}-${targetId}`;
    if (edges.some(e => e.id === edgeId)) return;
    edges.push({
      id: edgeId,
      sourceId,
      targetId,
    });
  }

  for (let i = 0; i < layers.length; i++) {
    const layer = layers[i];
    const nextLayer = layers[i + 1];

    if (layer.type === 'human' && nextLayer?.type === 'ai') {
      const sourceId = findNodeId('human', layer.stepNumbers[0])!;
      const targetId = findNodeId('ai', nextLayer.stepNumbers[0])!;
      addEdge(sourceId, targetId);
    }
    else if (layer.type === 'ai' && nextLayer?.type === 'tools') {
      // AI → Tools (fan-out)
      const aiNodeId = findNodeId('ai', layer.stepNumbers[0])!;
      if (nextLayer.toolInfos) {
        nextLayer.toolInfos.forEach((_, idx) => {
          const toolNodeId = findToolNodeId(i + 1, idx);
          if (toolNodeId && aiNodeId) {
            addEdge(aiNodeId, toolNodeId);
          }
        });
      }
    }
    else if (layer.type === 'tools' && nextLayer?.type === 'ai') {
      // Tools → Next AI (fan-in)
      const targetId = findNodeId('ai', nextLayer.stepNumbers[0])!;
      if (targetId && layer.toolInfos) {
        layer.toolInfos.forEach((_, idx) => {
          const toolNodeId = findToolNodeId(i, idx);
          if (toolNodeId) {
            addEdge(toolNodeId, targetId);
          }
        });
      }
    }
    else if (layer.type === 'ai' && nextLayer?.type === 'ai') {
      // AI → AI (final response)
      const sourceId = findNodeId('ai', layer.stepNumbers[0])!;
      const targetId = findNodeId('ai', nextLayer.stepNumbers[0])!;
      if (sourceId && targetId) addEdge(sourceId, targetId);
    }
  }

  return edges;
}

// ============================================================================
// Utility functions
// ============================================================================

export function truncateForDAG(text: string, maxLength: number = 80): string {
  if (!text) return '';
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength) + '...';
}

export function formatToolOutput(output: string, maxLength: number = 150): string {
  if (!output) return '(no output)';
  try {
    const parsed = JSON.parse(output);
    const formatted = JSON.stringify(parsed, null, 2);
    if (formatted.length <= maxLength) return formatted;
  } catch {
    // Not JSON
  }
  return truncateForDAG(output, maxLength);
}

/**
 * Calculate the bounding box for all nodes
 */
export function calculateBoundingBox(nodes: LayoutNode[]): { width: number; height: number; minX: number; minY: number } {
  if (nodes.length === 0) {
    return { width: 400, height: 300, minX: 0, minY: 0 };
  }

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  for (const node of nodes) {
    minX = Math.min(minX, node.x);
    minY = Math.min(minY, node.y);
    maxX = Math.max(maxX, node.x + node.width);
    maxY = Math.max(maxY, node.y + node.height);
  }

  return {
    width: maxX - minX + 160, // padding (extra for centering)
    height: maxY - minY + 160, // padding (extra for top/bottom)
    minX,
    minY,
  };
}