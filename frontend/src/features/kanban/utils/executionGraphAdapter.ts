import type {
  AINodeData,
  DAGNodeData,
  DAGResult,
  ExecutionDagRaw,
  ExecutionGraphEdgeRaw,
  ExecutionGraphNodeRaw,
  LayoutEdge,
  LayoutNode,
  MessageStepRaw,
} from '../types/dag';
import { layoutDAG } from './dagLayout';
import { measureDAGNode } from './dagNodeMetrics';

export function adaptExecutionDag(dag: ExecutionDagRaw): DAGResult {
  if (dag.execution_graph?.contract_version === 'execution-graph-v2') {
    return adaptRuntimeGraph(dag.execution_graph.nodes, dag.execution_graph.edges, dag.steps);
  }
  if (dag.nodes.length > 0) {
    return adaptLegacyDag(dag);
  }
  return layoutDAG([], [], emptySummary());
}

function adaptRuntimeGraph(
  graphNodes: ExecutionGraphNodeRaw[],
  graphEdges: ExecutionGraphEdgeRaw[],
  steps: MessageStepRaw[],
): DAGResult {
  const byActionId = new Map<string, MessageStepRaw>();
  for (const step of steps) {
    const actionId = step.action_id || step.tool_call_id;
    if (actionId) byActionId.set(actionId, step);
  }
  const humanStep = steps.find(step => step.message_type === 'human');
  const responseStep = [...steps].reverse().find(step => step.message_type === 'ai');
  const nodes = graphNodes.map(node => {
    const step =
      node.kind === 'action' && node.action_id
        ? byActionId.get(node.action_id)
        : node.kind === 'user'
          ? humanStep
          : responseStep;
    return displayNode(node, step);
  });
  const edges: LayoutEdge[] = graphEdges.map(edge => ({
    id: edge.edge_id,
    sourceId: edge.source_id,
    targetId: edge.target_id,
    relation: edge.relation,
  }));
  const toolCount = graphNodes.filter(node => node.kind === 'action').length;
  return layoutDAG(nodes, edges, {
    totalToolCalls: toolCount,
    totalSteps: graphNodes.length,
    hasThinking: Boolean(responseStep?.thinking || responseStep?.thinking_status),
    modelName: responseStep?.model_name,
  });
}

function displayNode(
  node: ExecutionGraphNodeRaw,
  step: MessageStepRaw | undefined,
): LayoutNode {
  let data: DAGNodeData;
  if (node.kind === 'user') {
    data = {
      type: 'human',
      content: step?.content || '',
      stepNumber: node.step_number,
    };
  } else if (node.kind === 'response') {
    data = aiNodeData(step, node.step_number);
  } else {
    data = {
      type: 'tool',
      toolName: node.operation || node.label,
      toolArgs: step?.tool_args || null,
      toolOutput: step?.tool_output || null,
      toolStatus: node.status || step?.tool_status || null,
      toolError: step?.tool_error || null,
      index: Math.max(0, node.order - 1),
      stepNumber: node.step_number,
    };
  }
  const size = measureForData(data);
  return {
    id: node.node_id,
    data,
    x: 0,
    y: 0,
    width: size.width,
    height: size.height,
  };
}

function adaptLegacyDag(dag: ExecutionDagRaw): DAGResult {
  const nodes = dag.nodes.map(raw => {
    const step = raw.step;
    let data: DAGNodeData;
    if (raw.message_type === 'human') {
      data = {
        type: 'human',
        content: step.content || '',
        stepNumber: raw.step_number,
      };
    } else if (raw.message_type === 'tool') {
      data = {
        type: 'tool',
        toolName: step.tool_name || raw.node_name,
        toolArgs: step.tool_args || null,
        toolOutput: step.tool_output || null,
        toolStatus: step.tool_status || null,
        toolError: step.tool_error || null,
        index: raw.step_number,
        stepNumber: raw.step_number,
      };
    } else {
      data = aiNodeData(step, raw.step_number);
    }
    const size = measureForData(data);
    return {
      id: raw.node_id,
      data,
      x: 0,
      y: 0,
      width: size.width,
      height: size.height,
    };
  });
  const edges: LayoutEdge[] = dag.edges.map(([sourceId, targetId], index) => ({
    id: `legacy-edge-${index}-${sourceId}-${targetId}`,
    sourceId,
    targetId,
    relation: 'legacy',
  }));
  return layoutDAG(nodes, edges, {
    totalToolCalls: dag.nodes.filter(node => node.message_type === 'tool').length,
    totalSteps: dag.nodes.length,
    hasThinking: dag.steps.some(step => Boolean(step.thinking || step.thinking_status)),
    modelName: dag.steps.find(step => step.model_name)?.model_name,
  });
}

function aiNodeData(
  step: MessageStepRaw | undefined,
  stepNumber: number,
): AINodeData {
  return {
    type: 'ai',
    thinking: step?.thinking,
    thinkingStatus: step?.thinking_status,
    toolCalls: step?.tool_calls,
    content: step?.content,
    modelName: step?.model_name,
    stepNumber,
    isFinal: true,
  };
}

function measureForData(data: DAGNodeData): { width: number; height: number } {
  if (data.type === 'human') return measureDAGNode('human', {});
  if (data.type === 'ai') {
    return measureDAGNode('ai', {
      thinking: data.thinking,
      thinkingStatus: data.thinkingStatus,
    });
  }
  if (data.type === 'tool') {
    return measureDAGNode('tool', { toolName: data.toolName });
  }
  return { width: 120, height: 58 };
}

function emptySummary(): DAGResult['summary'] {
  return {
    totalToolCalls: 0,
    totalSteps: 0,
    hasThinking: false,
  };
}
