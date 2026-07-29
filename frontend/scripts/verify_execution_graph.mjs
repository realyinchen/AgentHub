import path from "node:path"
import { fileURLToPath } from "node:url"

import { createServer } from "vite"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const frontendRoot = path.resolve(__dirname, "..")

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const operations = [
  "start_research",
  "plan_research_search",
  "acquire_research_sources",
  "collect_research_sources",
  "add_evidence",
  "evaluate_research_gaps",
  "plan_research_search",
  "acquire_research_sources",
  "collect_research_sources",
  "add_evidence",
  "evaluate_research_gaps",
  "build_research_report",
  "synthesize_research_answer",
  "publish_research_answer",
]

const graphNodes = [
  {
    node_id: "user:req",
    kind: "user",
    label: "用户",
    status: "input",
    order: 0,
    step_number: 1,
  },
  ...operations.map((operation, index) => ({
    node_id: `action:a${index + 1}`,
    kind: "action",
    label: operation,
    operation,
    action_id: `a${index + 1}`,
    capability: "research",
    status: "completed",
    order: index + 1,
    step_number: index + 2,
  })),
  {
    node_id: "response:req",
    kind: "response",
    label: "AI",
    status: "response",
    order: operations.length + 1,
    step_number: operations.length + 2,
  },
]

const graphEdges = [
  {
    edge_id: "entry",
    source_id: "user:req",
    target_id: "action:a1",
    relation: "entry",
  },
  ...operations.slice(1).map((_, index) => ({
    edge_id: `dependency-${index}`,
    source_id: `action:a${index + 1}`,
    target_id: `action:a${index + 2}`,
    relation: "dependency",
  })),
  {
    edge_id: "response",
    source_id: `action:a${operations.length}`,
    target_id: "response:req",
    relation: "response",
  },
]

const dag = {
  thread_id: "thread",
  nodes: [],
  edges: [],
  total_steps: graphNodes.length,
  steps: [
    {
      step_number: 1,
      message_type: "human",
      content: "深度搜索最新的好评动物图书",
    },
    ...operations.map((operation, index) => ({
      step_number: index + 2,
      message_type: "tool",
      tool_name: operation,
      action_id: `a${index + 1}`,
      tool_call_id: `a${index + 1}`,
      tool_status: "completed",
      tool_output: "{}",
    })),
    {
      step_number: operations.length + 2,
      message_type: "ai",
      content: "研究结论",
    },
  ],
  execution_graph: {
    contract_version: "execution-graph-v2",
    plan_id: "plan",
    request_id: "req",
    entry_node_id: "user:req",
    exit_node_id: "response:req",
    nodes: graphNodes,
    edges: graphEdges,
  },
}

const server = await createServer({
  root: frontendRoot,
  logLevel: "error",
  appType: "custom",
  server: { middlewareMode: true },
})

try {
  const { adaptExecutionDag } = await server.ssrLoadModule(
    "/src/features/kanban/utils/executionGraphAdapter.ts",
  )
  const result = adaptExecutionDag(dag)
  assert(result.nodes.length === graphNodes.length, "all graph nodes must render")
  assert(result.edges.length === graphEdges.length, "all dependency edges must render")

  const incoming = new Map(result.nodes.map(node => [node.id, 0]))
  for (const edge of result.edges) {
    assert(incoming.has(edge.sourceId), `unknown edge source ${edge.sourceId}`)
    assert(incoming.has(edge.targetId), `unknown edge target ${edge.targetId}`)
    incoming.set(edge.targetId, incoming.get(edge.targetId) + 1)
  }
  for (const [nodeId, count] of incoming) {
    if (nodeId !== "user:req") {
      assert(count > 0, `${nodeId} must have an incoming edge`)
    }
  }

  const nodeMap = new Map(result.nodes.map(node => [node.id, node]))
  for (const edge of result.edges) {
    const source = nodeMap.get(edge.sourceId)
    const target = nodeMap.get(edge.targetId)
    assert(source.y + source.height < target.y, `${edge.id} must flow downward`)
  }
  for (const node of result.nodes) {
    assert(node.x >= result.bounds.x, `${node.id} clipped on left`)
    assert(node.y >= result.bounds.y, `${node.id} clipped on top`)
    assert(
      node.x + node.width <= result.bounds.x + result.bounds.width,
      `${node.id} clipped on right`,
    )
    assert(
      node.y + node.height <= result.bounds.y + result.bounds.height,
      `${node.id} clipped on bottom`,
    )
  }
  const { default: CSSTurnDAG } = await server.ssrLoadModule(
    "/src/features/kanban/components/dag/CSSTurnDAG.tsx",
  )
  const { I18nProvider } = await server.ssrLoadModule("/src/i18n/index.tsx")
  const html = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(CSSTurnDAG, { dag, compact: true }),
    ),
  )
  assert(html.includes("<foreignObject"), "graph nodes must render in one SVG viewport")
  assert(html.includes("<path"), "graph edges must render as SVG paths")
  assert(html.includes("viewBox="), "graph must use one SVG viewBox")
  assert(!html.includes("scale("), "compact graph must not use a second CSS scale")
  console.log("verify_execution_graph: ok")
} finally {
  await server.close()
}
