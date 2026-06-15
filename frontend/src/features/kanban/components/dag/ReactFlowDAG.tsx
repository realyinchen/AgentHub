/**
 * ReactFlowDAG - Cyberpunk-themed DAG visualization using React Flow.
 * Fixed dark theme (#0a0e17 background) — all colors hardcoded.
 *
 * Features:
 * - Rounded-rectangle glow nodes with color-coded roles
 * - Gradient bezier edges with flowing light animation
 * - Drag, zoom, click-to-select interactions
 * - Compact mode for sidebar (read-only, fit view with lower zoom)
 * - onNodeClick callback for detail sheet integration
 */

import { useCallback, useEffect, useRef } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Node,
  type FitViewOptions,
  type NodeMouseHandler,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { useDAGFlow, type FlowNodeData } from './hooks/useDAGFlow';
import BaseNode from './nodes/BaseNode';
import GlowEdge from './edges/GlowEdge';
import type { MessageStepRaw } from '../../types/dag';
import type { DAGNodeData } from '../../types/dag';

// ============================================================================
// Props
// ============================================================================

interface ReactFlowDAGProps {
  steps: MessageStepRaw[];
  /** Compact mode: no interactions, smaller, fit view */
  compact?: boolean;
  className?: string;
  /** Called when a node is clicked, passing the raw DAG node data for detail sheet */
  onNodeClick?: (nodeData: DAGNodeData) => void;
  /** Hide MiniMap overlay (useful for dialog mode, keeps Controls) */
  hideMiniMap?: boolean;
}

// ============================================================================
// Custom node types (all use the same BaseNode, differentiated by type field)
// ============================================================================

const nodeTypes = {
  'user': BaseNode,
  'tool': BaseNode,
  'middle-ai': BaseNode,
  'final-ai': BaseNode,
};

// ============================================================================
// Custom edge types
// ============================================================================

const edgeTypes = {
  glow: GlowEdge,
};

// ============================================================================
// Fit view options
// ============================================================================

const defaultFitViewOptions: FitViewOptions = {
  padding: 0.3,
  maxZoom: 1.5,
  minZoom: 0.5,
};

const compactFitViewOptions: FitViewOptions = {
  padding: 0.4,
  maxZoom: 0.6,
  minZoom: 0.2,
};

// ============================================================================
// MiniMap node colors
// ============================================================================

const minimapNodeColor = (node: Node) => {
  const data = node.data as FlowNodeData | undefined;
  switch (data?.type) {
    case 'user': return '#3B82F6';
    case 'tool': return '#8B5CF6';
    case 'middle-ai': return '#F59E0B';
    case 'final-ai': return '#10B981';
    default: return '#6B7A90';
  }
};

// ============================================================================
// Inner child component — renders inside <ReactFlow> so useReactFlow() works
// ============================================================================

interface DAGCanvasProps {
  compact: boolean;
  hideMiniMap?: boolean;
}

function DAGCanvas({ compact, hideMiniMap = false }: DAGCanvasProps) {
  const { fitView } = useReactFlow();

  // One-time fitView after mount — use rAF to avoid visible jump
  const hasFitted = useRef(false);

  useEffect(() => {
    if (!hasFitted.current) {
      const raf = requestAnimationFrame(() => {
        fitView(compact ? compactFitViewOptions : defaultFitViewOptions);
        hasFitted.current = true;
      });
      return () => cancelAnimationFrame(raf);
    }
  }, [fitView, compact]);

  return (
    <>
      {/* Grid background (subtle) */}
      <Background
        color="#1A2540"
        gap={40}
        size={0.5}
      />

      {/* Controls (always shown in non-compact mode, no interactivity toggle) */}
      {!compact && (
        <Controls
          showInteractive={false}
          className="[&>button]:!bg-[#111827] [&>button]:!border-[#1E293B] [&>button]:!text-[#6B7A90] [&>button:hover]:!bg-[#1E293B] [&>button:hover]:!text-[#E6EDF3] [&>svg]:!fill-[#6B7A90]"
          style={{
            background: '#111827',
            border: '1px solid #1E293B',
            borderRadius: '8px',
          }}
        />
      )}

      {/* MiniMap (hidden in compact mode or when hideMiniMap is set) */}
      {!compact && !hideMiniMap && (
        <MiniMap
          nodeColor={minimapNodeColor}
          maskColor="rgba(10, 14, 23, 0.7)"
          style={{
            background: '#111827',
            border: '1px solid #1E293B',
            borderRadius: '8px',
          }}
        />
      )}
    </>
  );
}

// ============================================================================
// Main component — owns nodes/edges state, renders <ReactFlow>
// ============================================================================

function ReactFlowDAG({ steps, compact = false, className = '', onNodeClick, hideMiniMap = false }: ReactFlowDAGProps) {
  const { nodes: initialNodes, edges: initialEdges } = useDAGFlow(steps);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Track data version so DAGCanvas knows when to re-fit
  const dataVersionRef = useRef(0);

  // Update nodes/edges when steps change
  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
    dataVersionRef.current += 1;
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  // Node click handler
  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      const data = node.data as FlowNodeData;
      if (data?.rawData && onNodeClick) {
        onNodeClick(data.rawData as DAGNodeData);
      }
    },
    [onNodeClick],
  );

  // If no steps, show empty state
  if (steps.length === 0) {
    return (
      <div
        className={`flex items-center justify-center ${className}`}
        style={{ background: '#0a0e17', minHeight: 200 }}
      >
        <span style={{ color: '#6B7A90', fontSize: 13 }}>
          No execution steps
        </span>
      </div>
    );
  }

  return (
    <div
      className={className || 'relative h-full'}
      style={{ background: '#0a0e17', borderRadius: '12px', overflow: 'hidden' }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={compact ? undefined : onNodesChange}
        onEdgesChange={compact ? undefined : onEdgesChange}
        onNodeClick={onNodeClick ? handleNodeClick : undefined}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodesDraggable={!compact}
        nodesConnectable={false}
        elementsSelectable={!compact}
        panOnDrag={!compact}
        zoomOnScroll={!compact}
        zoomOnDoubleClick={!compact}
        minZoom={compact ? 0.15 : 0.3}
        maxZoom={compact ? 0.8 : 2}
        defaultViewport={{ x: 0, y: 0, zoom: compact ? 0.4 : 0.8 }}
        proOptions={{ hideAttribution: true }}
        style={{ background: '#0a0e17', width: '100%', height: '100%' }}
      >
        <DAGCanvas
          key={dataVersionRef.current}
          compact={compact}
          hideMiniMap={hideMiniMap}
        />
      </ReactFlow>
    </div>
  );
}

export default ReactFlowDAG;
