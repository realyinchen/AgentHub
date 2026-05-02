/**
 * CSSTurnDAG - Pure CSS DAG visualization for a single turn.
 * No third-party graph library — uses absolute positioning + SVG edges.
 */

import { useMemo, useState, useCallback, useRef } from 'react';
import { ZoomIn, ZoomOut, Maximize2, Minimize2 } from 'lucide-react';

import type { MessageStepRaw, LayoutNode, DAGNodeData } from '../../types/dag';
import { buildDAGFromSteps, calculateBoundingBox } from '../../utils/dagBuilder';
import { DARK_THEME } from '../../styles/theme';
import NodeDetailSheet from './NodeDetailSheet';

interface CSSTurnDAGProps {
  steps: MessageStepRaw[];
  className?: string;
}

function CSSTurnDAG({ steps, className = '' }: CSSTurnDAGProps) {
  const [selectedNode, setSelectedNode] = useState<DAGNodeData | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [scale, setScale] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const { nodes, edges, summary } = useMemo(() => buildDAGFromSteps(steps), [steps]);
  const bbox = useMemo(() => calculateBoundingBox(nodes), [nodes]);

  // Node map for quick edge lookup
  const nodeMap = useMemo(() => {
    const map = new Map<string, LayoutNode>();
    for (const node of nodes) {
      map.set(node.id, node);
    }
    return map;
  }, [nodes]);

  const onNodeClick = useCallback((nodeData: DAGNodeData) => {
    setSelectedNode(nodeData);
    setSheetOpen(true);
  }, []);

  const onSheetOpenChange = useCallback((open: boolean) => {
    setSheetOpen(open);
    if (!open) setSelectedNode(null);
  }, []);

  const zoomIn = useCallback(() => setScale(s => Math.min(s + 0.15, 2.5)), []);
  const zoomOut = useCallback(() => setScale(s => Math.max(s - 0.15, 0.3)), []);
  const resetZoom = useCallback(() => setScale(1), []);

  const toggleFullscreen = useCallback(() => {
    if (!isFullscreen && containerRef.current?.requestFullscreen) {
      containerRef.current.requestFullscreen();
      setIsFullscreen(true);
    } else if (document.fullscreenElement) {
      document.exitFullscreen();
      setIsFullscreen(false);
    }
  }, [isFullscreen]);

  if (nodes.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-[200px]"
        style={{ color: DARK_THEME.textDim }}
      >
        No steps to display
      </div>
    );
  }

  // Offset to center the graph (shift so minX/minY map to padding)
  // Add extra padding at top to ensure human node is fully visible
  const offsetX = -bbox.minX + 60;
  const offsetY = -bbox.minY + 80;

  return (
    <>
      <div
        ref={containerRef}
        className={`relative ${className}`}
        style={{
          height: isFullscreen ? '100vh' : Math.max(280, Math.min(500, bbox.height * scale + 80)),
          background: DARK_THEME.bgMain,
          borderRadius: '12px',
          border: `1px solid ${DARK_THEME.border}`,
          overflow: 'auto',
        }}
      >
        {/* Zoom controls */}
        <div
          className="absolute top-3 right-3 flex items-center gap-1 px-2 py-1 rounded-lg z-10"
          style={{
            background: DARK_THEME.bgPanel,
            border: `1px solid ${DARK_THEME.border}`,
          }}
        >
          <button
            onClick={zoomOut}
            className="p-1.5 rounded-md transition-colors cursor-pointer"
            style={{ color: DARK_THEME.textSecondary }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.06)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={resetZoom}
            className="px-2 py-0.5 text-xs rounded-md transition-colors cursor-pointer"
            style={{
              color: DARK_THEME.textSecondary,
              fontVariantNumeric: 'tabular-nums',
              minWidth: '40px',
              textAlign: 'center',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.06)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            {Math.round(scale * 100)}%
          </button>
          <button
            onClick={zoomIn}
            className="p-1.5 rounded-md transition-colors cursor-pointer"
            style={{ color: DARK_THEME.textSecondary }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.06)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <div style={{ width: 1, height: 16, background: DARK_THEME.border, margin: '0 4px' }} />
          <button
            onClick={toggleFullscreen}
            className="p-1.5 rounded-md transition-colors cursor-pointer"
            style={{ color: DARK_THEME.textSecondary }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.06)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </button>
        </div>

        {/* Scrollable canvas area */}
        <div
          className="w-full overflow-auto"
          style={{
            height: '100%',
            paddingTop: '40px',
            scrollbarColor: `${DARK_THEME.border} transparent`,
          }}
        >
          <div
            style={{
              width: bbox.width,
              height: bbox.height,
              position: 'relative',
              transform: `scale(${scale})`,
              transformOrigin: 'top center',
              transition: 'transform 0.15s ease',
              margin: '0 auto',
            }}
          >
            {/* SVG Edges layer */}
            <svg
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                pointerEvents: 'none',
                overflow: 'visible',
              }}
            >
              <defs>
                <marker
                  id="dag-arrow"
                  markerWidth="10"
                  markerHeight="7"
                  refX="9"
                  refY="3.5"
                  orient="auto"
                  markerUnits="strokeWidth"
                >
                  <polygon
                    points="0 0, 10 3.5, 0 7"
                    fill={DARK_THEME.edgeColor}
                  />
                </marker>
              </defs>
              {edges.map(edge => {
                const sourceNode = nodeMap.get(edge.sourceId);
                const targetNode = nodeMap.get(edge.targetId);
                if (!sourceNode || !targetNode) return null;

                const sx = sourceNode.x + offsetX + sourceNode.width / 2;
                const sy = sourceNode.y + offsetY + sourceNode.height;
                const tx = targetNode.x + offsetX + targetNode.width / 2;
                const ty = targetNode.y + offsetY;

                return (
                  <line
                    key={edge.id}
                    x1={sx}
                    y1={sy}
                    x2={tx}
                    y2={ty}
                    stroke={DARK_THEME.edgeColor}
                    strokeWidth={2}
                    markerEnd="url(#dag-arrow)"
                    strokeDasharray="5 5"
                    opacity={0.6}
                    style={{
                      animation: `edgeFlow 1s linear infinite`,
                    }}
                  />
                );
              })}
            </svg>

            {/* Nodes layer */}
            {nodes.map((node, idx) => {
              const x = node.x + offsetX;
              const y = node.y + offsetY;

              return (
                <div
                  key={node.id}
                  onClick={() => onNodeClick(node.data)}
                  className="absolute cursor-pointer"
                  style={{
                    left: x,
                    top: y,
                    width: node.width,
                    transition: 'transform 0.15s ease',
                    animation: `nodeAppear 0.3s ease ${idx * 0.05}s both`,
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.transform = 'translateY(-2px)';
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.transform = 'translateY(0)';
                  }}
                >
                  <DAGNodeCard data={node.data} />
                </div>
              );
            })}
          </div>
        </div>

        {/* Summary footer */}
        <div
          className="absolute bottom-2 left-2 flex items-center gap-2 text-xs px-3 py-1.5 rounded-md z-10"
          style={{
            background: DARK_THEME.bgPanel,
            border: `1px solid ${DARK_THEME.border}`,
            color: DARK_THEME.textSecondary,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <span>{summary.totalSteps} steps</span>
          <span style={{ color: DARK_THEME.textDim }}>·</span>
          <span>{summary.totalToolCalls} tool calls</span>
          {summary.hasThinking && (
            <>
              <span style={{ color: DARK_THEME.textDim }}>·</span>
              <span>thinking</span>
            </>
          )}
        </div>

        {/* Hint */}
        <div
          className="absolute top-3 left-3 text-xs px-3 py-1.5 rounded-md z-10"
          style={{
            background: DARK_THEME.bgPanel,
            border: `1px solid ${DARK_THEME.border}`,
            color: DARK_THEME.textDim,
          }}
        >
          Click nodes to view details
        </div>
      </div>

      <NodeDetailSheet
        nodeData={selectedNode}
        open={sheetOpen}
        onOpenChange={onSheetOpenChange}
      />
    </>
  );
}

// ============================================================================
// Individual node card renderer
// ============================================================================

function DAGNodeCard({ data }: { data: DAGNodeData }) {
  switch (data.type) {
    case 'human':
      return <HumanCard data={data} />;
    case 'ai':
      return <AICard data={data} />;
    case 'tool':
      return <ToolCard data={data} />;
    case 'subagent':
      return <SubAgentCard data={data} />;
    default:
      return null;
  }
}

// ============================================================================
// Human Node — Purple (#A78BFA)
// ============================================================================

function HumanCard({ data: _data }: { data: { type: 'human'; content: string; stepNumber: number } }) {
  return (
    <div
      style={{
        background: DARK_THEME.bgPanel,
        border: `1px solid ${DARK_THEME.nodeUserBorder}`,
        borderRadius: '10px',
        padding: '12px 16px',
      }}
    >
      <div className="flex items-center gap-2">
        <div
          className="flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0"
          style={{
            background: DARK_THEME.nodeUserLight,
            border: `1px solid ${DARK_THEME.nodeUserBorder}`,
          }}
        >
          <span className="text-xs" style={{ color: DARK_THEME.nodeUser }}>👤</span>
        </div>
        <span className="text-sm font-medium truncate" style={{ color: DARK_THEME.nodeUser }}>
          User
        </span>
      </div>
    </div>
  );
}

// ============================================================================
// AI Node — Blue (#5B8CFF)
// ============================================================================

function AICard({ data }: { data: { type: 'ai'; modelName?: string | null; isFinal: boolean; toolCalls?: { name: string }[] | null; thinking?: string | null } }) {
  const borderColor = data.isFinal ? DARK_THEME.successBorder : DARK_THEME.nodeAIBorder;
  const iconBg = data.isFinal ? DARK_THEME.successLight : DARK_THEME.nodeAILight;
  const iconColor = data.isFinal ? DARK_THEME.success : DARK_THEME.nodeAI;
  const icon = data.isFinal ? '✅' : '🤖';

  return (
    <div
      style={{
        background: DARK_THEME.bgPanel,
        border: `1px solid ${borderColor}`,
        borderRadius: '10px',
        padding: '12px 16px',
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className="flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0"
            style={{
              background: iconBg,
              border: `1px solid ${borderColor}`,
            }}
          >
            <span className="text-xs">{icon}</span>
          </div>
          <span className="text-sm font-medium truncate" style={{ color: iconColor }}>
            {data.modelName || 'AI'}
          </span>
        </div>
        {data.isFinal && (
          <span
            className="text-xs px-1.5 py-0.5 rounded flex-shrink-0"
            style={{ background: DARK_THEME.successLight, color: DARK_THEME.success }}
          >
            Final
          </span>
        )}
      </div>
      {(data.toolCalls && data.toolCalls.length > 0) && (
        <div className="text-xs mt-1.5" style={{ color: DARK_THEME.textDim }}>
          🔧 {data.toolCalls.length} tool calls
        </div>
      )}
      {data.thinking && !data.toolCalls?.length && (
        <div className="text-xs mt-1.5" style={{ color: DARK_THEME.nodeAI }}>
          🧠 thinking...
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Tool Node — Yellow (#F59E0B)
// ============================================================================

function ToolCard({ data }: { data: { type: 'tool'; toolName: string; toolOutput: string | null } }) {
  const status = !data.toolOutput
    ? 'pending'
    : data.toolOutput === '...'
      ? 'running'
      : data.toolOutput.includes('error') || data.toolOutput.includes('Error')
        ? 'error'
        : 'success';

  const statusText = {
    pending: 'Waiting...',
    running: 'Executing...',
    success: 'Completed',
    error: 'Failed',
  }[status];

  const statusIcon = {
    pending: '⏳',
    running: '🔄',
    success: '✓',
    error: '✗',
  }[status];

  const statusColor = {
    pending: DARK_THEME.textDim,
    running: DARK_THEME.nodeTool,
    success: DARK_THEME.success,
    error: DARK_THEME.error,
  }[status];

  return (
    <div
      style={{
        background: DARK_THEME.bgPanel,
        border: `1px solid ${DARK_THEME.nodeToolBorder}`,
        borderRadius: '10px',
        padding: '12px 16px',
      }}
    >
      <div className="flex items-center gap-2">
        <div
          className="flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0"
          style={{
            background: DARK_THEME.nodeToolLight,
            border: `1px solid ${DARK_THEME.nodeToolBorder}`,
          }}
        >
          <span className="text-xs">🔧</span>
        </div>
        <span className="text-sm font-medium truncate" style={{ color: DARK_THEME.textPrimary }}>
          {data.toolName}
        </span>
      </div>
      <div className="flex items-center gap-1.5 mt-1.5">
        <span className="text-xs" style={{ color: statusColor }}>{statusIcon}</span>
        <span className="text-xs" style={{ color: DARK_THEME.textDim }}>{statusText}</span>
      </div>
    </div>
  );
}

// ============================================================================
// SubAgent Node — Blue Gradient (#5B8CFF → #06B6D4)
// ============================================================================

function SubAgentCard({ data }: { data: { type: 'subagent'; agentName: string; modelName?: string | null } }) {
  return (
    <div
      style={{
        background: DARK_THEME.bgPanel,
        border: `2px solid transparent`,
        borderImage: `linear-gradient(135deg, ${DARK_THEME.nodeSubagentFrom}, ${DARK_THEME.nodeSubagentTo}) 1`,
        borderRadius: '10px',
        padding: '12px 16px',
      }}
    >
      <div className="flex items-center gap-2">
        <div
          className="flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0"
          style={{
            background: DARK_THEME.nodeAILight,
            border: `1px solid ${DARK_THEME.nodeAIBorder}`,
          }}
        >
          <span className="text-xs">🔄</span>
        </div>
        <span className="text-sm font-medium truncate" style={{ color: DARK_THEME.nodeAI }}>
          {data.agentName}
        </span>
      </div>
    </div>
  );
}

export default CSSTurnDAG;