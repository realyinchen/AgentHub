/**
 * CSSTurnDAG - Pure CSS DAG visualization for a single turn.
 * No third-party graph library — uses absolute positioning + SVG edges.
 */

import { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { ZoomIn, ZoomOut, Maximize2, Minimize2 } from 'lucide-react';

import type { MessageStepRaw, LayoutNode, DAGNodeData } from '../../types/dag';
import { buildDAGFromSteps, calculateBoundingBox } from '../../utils/dagBuilder';
import NodeDetailSheet from './NodeDetailSheet';
import { useI18n } from '@/i18n';

interface CSSTurnDAGProps {
  steps: MessageStepRaw[];
  className?: string;
  compact?: boolean; // Compact mode: hide controls, auto-scale to fit
}

function CSSTurnDAG({ steps, className = '', compact = false }: CSSTurnDAGProps) {
  const { t } = useI18n();
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

  // Auto-scale for compact mode: calculate scale to fit container both width AND height
  const [autoScale, setAutoScale] = useState(1);
  useEffect(() => {
    if (compact && containerRef.current) {
      const calculateAutoScale = () => {
        const containerWidth = containerRef.current?.clientWidth || 256;
        const containerHeight = containerRef.current?.clientHeight || 200;
        const dagWidth = bbox.width || 400;
        const dagHeight = bbox.height || 300;
        // Leave some padding and ensure scale fits both dimensions
        const scaleX = Math.min(1, (containerWidth - 20) / dagWidth);
        const scaleY = Math.min(1, (containerHeight - 20) / dagHeight);
        const calculatedScale = Math.min(scaleX, scaleY);
        setAutoScale(Math.max(0.2, calculatedScale));
      };

      calculateAutoScale();

      // Recalculate on resize
      const handleResize = () => calculateAutoScale();
      window.addEventListener('resize', handleResize);
      return () => window.removeEventListener('resize', handleResize);
    }
  }, [compact, bbox.width, bbox.height]);

  // Use auto-scale when in compact mode, otherwise use manual scale
  const effectiveScale = compact ? autoScale : scale;

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
        className="flex items-center justify-center h-[200px] text-muted-foreground"
      >
        {t('process.noSteps')}
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
          height: compact ? '100%' : (isFullscreen ? '100vh' : Math.max(280, Math.min(500, bbox.height * effectiveScale + 80))),
          background: 'var(--dag-bg-main)',
          borderRadius: '12px',
          border: '1px solid var(--dag-border)',
          overflow: compact ? 'hidden' : 'auto',
        }}
      >
        {/* Zoom controls - hidden in compact mode */}
        {!compact && (
          <div
            className="absolute top-3 right-3 flex items-center gap-1 px-2 py-1 rounded-lg z-10"
            style={{
              background: 'var(--dag-bg-panel)',
              border: '1px solid var(--dag-border)',
            }}
          >
            <button
              onClick={zoomOut}
              className="p-1.5 rounded-md transition-colors cursor-pointer text-muted-foreground hover:text-foreground hover:bg-muted/50"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={resetZoom}
              className="px-2 py-0.5 text-xs rounded-md transition-colors cursor-pointer text-muted-foreground hover:text-foreground hover:bg-muted/50"
              style={{
                fontVariantNumeric: 'tabular-nums',
                minWidth: '40px',
                textAlign: 'center',
              }}
            >
              {Math.round(scale * 100)}%
            </button>
            <button
              onClick={zoomIn}
              className="p-1.5 rounded-md transition-colors cursor-pointer text-muted-foreground hover:text-foreground hover:bg-muted/50"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <div style={{ width: 1, height: 16, background: 'var(--dag-border)', margin: '0 4px' }} />
            <button
              onClick={toggleFullscreen}
              className="p-1.5 rounded-md transition-colors cursor-pointer text-muted-foreground hover:text-foreground hover:bg-muted/50"
            >
              {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
            </button>
          </div>
        )}

        {/* Canvas area - centered in compact mode, scrollable otherwise */}
        <div
          className={compact ? 'w-full h-full' : 'w-full overflow-auto'}
          style={{
            height: '100%',
            ...(compact ? { display: 'flex', alignItems: 'center', justifyContent: 'center' } : { paddingTop: '40px' }),
          }}
        >
          <div
            style={{
              width: bbox.width,
              height: bbox.height,
              position: 'relative',
              transform: `scale(${effectiveScale})`,
              transformOrigin: compact ? 'center center' : 'top center',
              transition: 'transform 0.15s ease',
              margin: '0 auto',
              flexShrink: 0,
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
                    fill="var(--dag-edge)"
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
                    stroke="var(--dag-edge)"
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

        {/* Summary footer - hidden in compact mode */}
        {!compact && (
          <div
            className="absolute bottom-2 left-2 flex items-center gap-2 text-xs px-3 py-1.5 rounded-md z-10 text-muted-foreground"
            style={{
              background: 'var(--dag-bg-panel)',
              border: '1px solid var(--dag-border)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            <span>{summary.totalSteps} {t('process.steps')}</span>
            <span style={{ color: 'var(--dag-text-dim)' }}>·</span>
            <span>{summary.totalToolCalls} {t('process.toolCalls')}</span>
            {summary.hasThinking && (
              <>
                <span style={{ color: 'var(--dag-text-dim)' }}>·</span>
                <span>{t('process.thinking')}</span>
              </>
            )}
          </div>
        )}

        {/* Hint - hidden in compact mode */}
        {!compact && (
          <div
            className="absolute top-3 left-3 text-xs px-3 py-1.5 rounded-md z-10 text-muted-foreground"
            style={{
              background: 'var(--dag-bg-panel)',
              border: '1px solid var(--dag-border)',
            }}
          >
            {t('process.clickToView')}
          </div>
        )}
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
// Human Node — Gray
// ============================================================================

function HumanCard({ data: _data }: { data: { type: 'human'; content: string; stepNumber: number } }) {
  const { t } = useI18n();
  return (
    <div
      style={{
        background: 'var(--dag-bg-panel)',
        border: '1px solid var(--dag-node-user-border)',
        borderRadius: '10px',
        padding: '12px 16px',
      }}
    >
      <div className="flex items-center gap-2">
        <div
          className="flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0"
          style={{
            background: 'var(--dag-node-user-light)',
            border: '1px solid var(--dag-node-user-border)',
          }}
        >
          <span className="text-xs" style={{ color: 'var(--dag-node-user)' }}>👤</span>
        </div>
        <span className="text-sm font-medium truncate" style={{ color: 'var(--dag-node-user)' }}>
          {t('process.user')}
        </span>
      </div>
    </div>
  );
}

// ============================================================================
// AI Node — Blue
// ============================================================================

function AICard({ data }: { data: { type: 'ai'; modelName?: string | null; isFinal: boolean; toolCalls?: { name: string }[] | null; thinking?: string | null } }) {
  const { t } = useI18n();
  const borderColor = data.isFinal ? 'var(--dag-success-border)' : 'var(--dag-node-ai-border)';
  const iconBg = data.isFinal ? 'var(--dag-success-light)' : 'var(--dag-node-ai-light)';
  const iconColor = data.isFinal ? 'var(--dag-success)' : 'var(--dag-node-ai)';
  const icon = data.isFinal ? '✅' : '🤖';

  return (
    <div
      style={{
        background: 'var(--dag-bg-panel)',
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
            {data.modelName || t('process.ai')}
          </span>
        </div>
        {data.isFinal && (
          <span
            className="text-xs px-1.5 py-0.5 rounded flex-shrink-0"
            style={{ background: 'var(--dag-success-light)', color: 'var(--dag-success)' }}
          >
            {t('process.final')}
          </span>
        )}
      </div>
      {(data.toolCalls && data.toolCalls.length > 0) && (
        <div className="text-xs mt-1.5 text-muted-foreground">
          🔧 {data.toolCalls.length} {t('process.toolCalls')}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Tool Node — Purple
// ============================================================================

function ToolCard({ data }: { data: { type: 'tool'; toolName: string; toolOutput: string | null } }) {
  const { t } = useI18n();
  const status = !data.toolOutput
    ? 'pending'
    : data.toolOutput === '...'
      ? 'running'
      : data.toolOutput.includes('error') || data.toolOutput.includes('Error')
        ? 'error'
        : 'success';

  const statusText = {
    pending: t('process.toolStatus.pending'),
    running: t('process.toolStatus.running'),
    success: t('process.toolStatus.success'),
    error: t('process.toolStatus.error'),
  }[status];

  const statusIcon = {
    pending: '⏳',
    running: '🔄',
    success: '✓',
    error: '✗',
  }[status];

  const statusColor = {
    pending: 'var(--dag-text-dim)',
    running: 'var(--dag-node-tool)',
    success: 'var(--dag-success)',
    error: 'var(--dag-error)',
  }[status];

  return (
    <div
      style={{
        background: 'var(--dag-bg-panel)',
        border: '1px solid var(--dag-node-tool-border)',
        borderRadius: '10px',
        padding: '12px 16px',
      }}
    >
      <div className="flex items-center gap-2">
        <div
          className="flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0"
          style={{
            background: 'var(--dag-node-tool-light)',
            border: '1px solid var(--dag-node-tool-border)',
          }}
        >
          <span className="text-xs">🔧</span>
        </div>
        <span className="text-sm font-medium truncate" style={{ color: 'var(--dag-text-primary)' }}>
          {data.toolName}
        </span>
      </div>
      <div className="flex items-center gap-1.5 mt-1.5">
        <span className="text-xs" style={{ color: statusColor }}>{statusIcon}</span>
        <span className="text-xs text-muted-foreground">{statusText}</span>
      </div>
    </div>
  );
}

// ============================================================================
// SubAgent Node — Blue Gradient
// ============================================================================

function SubAgentCard({ data }: { data: { type: 'subagent'; agentName: string; modelName?: string | null } }) {
  return (
    <div
      style={{
        background: 'var(--dag-bg-panel)',
        border: '2px solid transparent',
        borderImage: 'linear-gradient(135deg, var(--dag-node-subagent-from), var(--dag-node-subagent-to)) 1',
        borderRadius: '10px',
        padding: '12px 16px',
      }}
    >
      <div className="flex items-center gap-2">
        <div
          className="flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0"
          style={{
            background: 'var(--dag-node-ai-light)',
            border: '1px solid var(--dag-node-ai-border)',
          }}
        >
          <span className="text-xs">🔄</span>
        </div>
        <span className="text-sm font-medium truncate" style={{ color: 'var(--dag-node-ai)' }}>
          {data.agentName}
        </span>
      </div>
    </div>
  );
}

export default CSSTurnDAG;