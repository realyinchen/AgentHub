/**
 * ReactFlowDAG - Theme-aware DAG visualization using React Flow.
 * All colors are CSS custom properties — adapts to light/dark themes.
 *
 * Features:
 * - Rounded-rectangle glow nodes with color-coded roles
 * - Gradient bezier edges with flowing light animation
 * - Drag, zoom, click-to-select interactions
 * - Compact mode for sidebar (read-only, fit view with lower zoom)
 * - onNodeClick callback for detail sheet integration
 */

import { useCallback, useEffect, useRef, useState } from 'react';
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
// MiniMap node colors (theme-aware via CSS variables)
// ============================================================================

const minimapNodeColor = (node: Node) => {
  const data = node.data as FlowNodeData | undefined;
  switch (data?.type) {
    case 'user': return 'var(--dag-node-human-border)';
    case 'tool': return 'var(--dag-node-tool-border)';
    case 'middle-ai': return 'var(--dag-node-ai-border)';
    case 'final-ai': return 'var(--dag-node-final-border)';
    default: return 'var(--dag-text-dim)';
  }
};

// ============================================================================
// Inner child component — renders inside <ReactFlow> so useReactFlow() works
// ============================================================================

interface DAGCanvasProps {
  compact: boolean;
  hideMiniMap?: boolean;
  containerRef: React.RefObject<HTMLDivElement | null>;
}

function DAGCanvas({ compact, hideMiniMap = false, containerRef }: DAGCanvasProps) {
  const { fitView } = useReactFlow();
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });
  const initialFitDone = useRef(false);

  // ResizeObserver: track container dimensions so DAG always fits
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setContainerSize({ width, height });
        }
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [containerRef]);

  // Re-fit whenever container size or data/compact mode changes
  useEffect(() => {
    const options = compact ? compactFitViewOptions : defaultFitViewOptions;
    if (containerSize.width === 0 && containerSize.height === 0) return;

    const delay = initialFitDone.current ? 50 : 100; // shorter delay for subsequent fits
    const timer = setTimeout(() => {
      fitView(options);
      initialFitDone.current = true;
    }, delay);
    return () => clearTimeout(timer);
  }, [fitView, compact, containerSize.width, containerSize.height]);

  return (
    <>
      {/* Grid background (subtle, theme-aware) */}
      <Background
        color="var(--dag-rf-grid)"
        gap={40}
        size={0.5}
      />

      {/* Controls (always shown in non-compact mode, no interactivity toggle) */}
      {!compact && (
        <Controls
          showInteractive={false}
          className="dag-rf-controls"
          style={{
            background: 'var(--dag-rf-controls-bg)',
            border: '1px solid var(--dag-rf-controls-border)',
            borderRadius: '8px',
          }}
        />
      )}

      {/* MiniMap (hidden in compact mode or when hideMiniMap is set) */}
      {!compact && !hideMiniMap && (
        <MiniMap
          nodeColor={minimapNodeColor}
          maskColor="var(--dag-rf-minimap-mask)"
          style={{
            background: 'var(--dag-rf-minimap-bg)',
            border: '1px solid var(--dag-rf-controls-border)',
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
        style={{ background: 'var(--dag-rf-background)', minHeight: 200 }}
      >
        <span style={{ color: 'var(--dag-rf-controls-text)', fontSize: 13 }}>
          No execution steps
        </span>
      </div>
    );
  }

  // Ref for the outer container div (used by ResizeObserver in DAGCanvas)
  const containerRef = useRef<HTMLDivElement | null>(null);

  return (
    <div
      ref={containerRef}
      className={className || 'relative h-full'}
      style={{ background: 'var(--dag-rf-background)', borderRadius: '12px', overflow: 'hidden' }}
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
        style={{ background: 'var(--dag-rf-background)', width: '100%', height: '100%' }}
      >
        <DAGCanvas
          key={dataVersionRef.current}
          compact={compact}
          hideMiniMap={hideMiniMap}
          containerRef={containerRef}
        />
      </ReactFlow>
    </div>
  );
}

export default ReactFlowDAG;
