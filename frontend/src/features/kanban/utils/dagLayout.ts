import type {
  DAGResult,
  LayoutBounds,
  LayoutEdge,
  LayoutNode,
} from '../types/dag';

const PADDING_X = 36;
const PADDING_Y = 32;
const LAYER_GAP_Y = 48;
const NODE_GAP_X = 40;

export function layoutDAG(
  inputNodes: LayoutNode[],
  inputEdges: LayoutEdge[],
  summary: DAGResult['summary'],
): DAGResult {
  if (inputNodes.length === 0) {
    return {
      nodes: [],
      edges: [],
      bounds: { x: 0, y: 0, width: 400, height: 300 },
      summary,
    };
  }

  const known = new Set(inputNodes.map(node => node.id));
  const edges = inputEdges.filter(
    edge => known.has(edge.sourceId) && known.has(edge.targetId),
  );
  const rankById = topologicalRanks(inputNodes, edges);
  const layers = new Map<number, LayoutNode[]>();
  for (const node of inputNodes) {
    const rank = rankById.get(node.id) ?? 0;
    const layer = layers.get(rank) ?? [];
    layer.push(node);
    layers.set(rank, layer);
  }
  for (const layer of layers.values()) {
    layer.sort((left, right) => left.data.stepNumber - right.data.stepNumber);
  }

  const orderedRanks = [...layers.keys()].sort((a, b) => a - b);
  const layerWidths = new Map<number, number>();
  const layerHeights = new Map<number, number>();
  for (const rank of orderedRanks) {
    const layer = layers.get(rank) ?? [];
    layerWidths.set(
      rank,
      layer.reduce(
        (sum, node, index) =>
          sum + node.width + (index < layer.length - 1 ? NODE_GAP_X : 0),
        0,
      ),
    );
    layerHeights.set(
      rank,
      Math.max(...layer.map(node => node.height), 0),
    );
  }

  const contentWidth = Math.max(...layerWidths.values(), 0);
  const positioned: LayoutNode[] = [];
  let y = PADDING_Y;
  for (const rank of orderedRanks) {
    const layer = layers.get(rank) ?? [];
    const layerWidth = layerWidths.get(rank) ?? 0;
    let x = PADDING_X + (contentWidth - layerWidth) / 2;
    for (const node of layer) {
      positioned.push({ ...node, x, y });
      x += node.width + NODE_GAP_X;
    }
    y += (layerHeights.get(rank) ?? 0) + LAYER_GAP_Y;
  }

  const lastRank = orderedRanks.at(-1) ?? 0;
  const contentHeight =
    y - LAYER_GAP_Y + PADDING_Y - (layerHeights.get(lastRank) ?? 0)
    + (layerHeights.get(lastRank) ?? 0);
  const bounds: LayoutBounds = {
    x: 0,
    y: 0,
    width: Math.max(160, contentWidth + PADDING_X * 2),
    height: Math.max(140, contentHeight),
  };
  return { nodes: positioned, edges, bounds, summary };
}

function topologicalRanks(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
): Map<string, number> {
  const indegree = new Map(nodes.map(node => [node.id, 0]));
  const outgoing = new Map<string, string[]>();
  for (const edge of edges) {
    indegree.set(edge.targetId, (indegree.get(edge.targetId) ?? 0) + 1);
    const targets = outgoing.get(edge.sourceId) ?? [];
    targets.push(edge.targetId);
    outgoing.set(edge.sourceId, targets);
  }
  const orderById = new Map(
    nodes.map(node => [node.id, node.data.stepNumber]),
  );
  const queue = nodes
    .filter(node => (indegree.get(node.id) ?? 0) === 0)
    .map(node => node.id)
    .sort((left, right) =>
      (orderById.get(left) ?? 0) - (orderById.get(right) ?? 0),
    );
  const ranks = new Map(nodes.map(node => [node.id, 0]));
  const visited = new Set<string>();

  while (queue.length > 0) {
    const sourceId = queue.shift()!;
    visited.add(sourceId);
    for (const targetId of outgoing.get(sourceId) ?? []) {
      ranks.set(
        targetId,
        Math.max(
          ranks.get(targetId) ?? 0,
          (ranks.get(sourceId) ?? 0) + 1,
        ),
      );
      indegree.set(targetId, (indegree.get(targetId) ?? 1) - 1);
      if ((indegree.get(targetId) ?? 0) === 0) {
        queue.push(targetId);
        queue.sort((left, right) =>
          (orderById.get(left) ?? 0) - (orderById.get(right) ?? 0),
        );
      }
    }
  }

  let fallbackRank = Math.max(...ranks.values(), 0) + 1;
  for (const node of [...nodes].sort(
    (left, right) => left.data.stepNumber - right.data.stepNumber,
  )) {
    if (!visited.has(node.id)) {
      ranks.set(node.id, fallbackRank);
      fallbackRank += 1;
    }
  }
  return ranks;
}
