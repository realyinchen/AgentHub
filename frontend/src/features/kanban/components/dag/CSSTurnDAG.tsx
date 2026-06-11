/**
 * CSSTurnDAG - Pure CSS DAG visualization for a single turn.
 * No third-party graph library — uses absolute positioning + SVG edges.
 */

import { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { Bot, Brain, CheckCircle2, ZoomIn, ZoomOut, Maximize2, Minimize2 } from 'lucide-react';

import type { MessageStepRaw, LayoutNode, DAGNodeData } from '../../types/dag';
import { buildDAGFromSteps, calculateBoundingBox } from '../../utils/dagBuilder';
import NodeDetailSheet from './NodeDetailSheet';
import { useI18n } from '@/i18n';
import { SciFiLoader } from '@/components/ai/neural-network-loader';

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

  // Auto-scale for compact mode: calculate scale to fill container both width AND height
  const [autoScale, setAutoScale] = useState(1);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  useEffect(() => {
    if (compact && containerRef.current) {
      const calculateAutoScale = () => {
        const containerWidth = containerRef.current?.clientWidth || 256;
        const containerHeight = containerRef.current?.clientHeight || 200;
        const dagWidth = bbox.width || 400;
        const dagHeight = bbox.height || 300;
        // No padding - fill the container completely
        const scaleX = containerWidth / dagWidth;
        const scaleY = containerHeight / dagHeight;
        // Use the smaller scale to ensure DAG fits, allow larger scaling
        const calculatedScale = Math.min(scaleX, scaleY, 4.0);
        setAutoScale(Math.max(0.5, calculatedScale));
      };

      calculateAutoScale();

      // Use ResizeObserver for better container size detection
      if (resizeObserverRef.current) {
        resizeObserverRef.current.disconnect();
      }
      resizeObserverRef.current = new ResizeObserver(() => {
        calculateAutoScale();
      });
      resizeObserverRef.current.observe(containerRef.current);

      return () => {
        if (resizeObserverRef.current) {
          resizeObserverRef.current.disconnect();
        }
      };
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
        className="flex items-center justify-center h-[200px]"
      >
        <SciFiLoader className="w-24 h-24" showText={false} />
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
          height: compact ? '100%' : (isFullscreen ? '100vh' : Math.max(280, Math.min(500, bbox.height * effectiveScale + 120))),
          background: 'var(--dag-bg-main)',
          borderRadius: '12px',
          border: '1px solid var(--dag-border)',
          overflow: compact ? 'hidden' : 'hidden',
          position: 'relative',
        }}
      >
        {/* Zoom controls - hidden in compact mode */}
        {!compact && (
          <div
            className="absolute top-3 right-3 flex items-center gap-1 px-2 py-1 rounded-lg"
            style={{
              background: 'var(--dag-bg-panel)',
              border: '1px solid var(--dag-border)',
              zIndex: 50,
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
          className={compact ? 'w-full h-full' : 'w-full overflow-auto dag-scroll-container'}
          style={{
            height: '100%',
            ...(compact ? { display: 'flex', alignItems: 'center', justifyContent: 'center' } : { paddingTop: '44px', paddingBottom: '44px' }),
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
                  markerWidth="8"
                  markerHeight="6"
                  refX="7"
                  refY="3"
                  orient="auto"
                  markerUnits="strokeWidth"
                >
                  <polygon
                    points="0 0, 8 3, 0 6"
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

                // Calculate orthogonal path with rounded corners
                // Use fixed vertical segments for cleaner look
                const verticalGap = 30; // Distance before horizontal turn
                const cornerRadius = 6;

                let pathD: string;

                if (Math.abs(sx - tx) < 1) {
                  // Direct vertical line (same x position)
                  pathD = `M ${sx},${sy} L ${tx},${ty}`;
                } else {
                  // Orthogonal path with rounded corners
                  // Go down from source, then horizontal at midpoint, then down to target
                  const turnY1 = sy + verticalGap;

                  pathD = `M ${sx},${sy} ` +
                    `L ${sx},${turnY1 - cornerRadius} ` +
                    `Q ${sx},${turnY1} ${sx + (tx > sx ? cornerRadius : -cornerRadius)},${turnY1} ` +
                    `L ${tx - (tx > sx ? cornerRadius : -cornerRadius)},${turnY1} ` +
                    `Q ${tx},${turnY1} ${tx},${turnY1 + cornerRadius} ` +
                    `L ${tx},${ty - cornerRadius * 2} ` +
                    `Q ${tx},${ty} ${tx},${ty}`;
                }

                return (
                  <path
                    key={edge.id}
                    d={pathD}
                    fill="none"
                    stroke="var(--dag-edge)"
                    strokeWidth={1.5}
                    markerEnd="url(#dag-arrow)"
                    opacity={0.5}
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
                    transition: 'transform 0.2s ease',
                    animation: `nodeAppear 0.5s ease ${idx * 0.08}s both`,
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.transform = 'translateY(-2px)';
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.transform = 'translateY(0)';
                  }}
                >
                  <DAGNodeCard data={node.data} width={node.width} />
                </div>
              );
            })}
          </div>
        </div>

        {/* Summary footer - hidden in compact mode */}
        {!compact && (
          <div
            className="absolute bottom-3 left-3 flex items-center gap-2 text-xs px-3 py-1.5 rounded-md z-10 text-muted-foreground"
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

function DAGNodeCard({ data, width }: { data: DAGNodeData; width: number }) {
  switch (data.type) {
    case 'human':
      return <HumanCard data={data} />;
    case 'ai':
      return <AICard data={data} />;
    case 'tool':
      return <ToolCard data={data} width={width} />;
    case 'subagent':
      return <SubAgentCard data={data} />;
    default:
      return null;
  }
}

// ============================================================================
// Human Node — Gray Blue
// ============================================================================

function HumanCard({ data: _data }: { data: { type: 'human'; content: string; stepNumber: number } }) {
  const { t } = useI18n();
  return (
    <div
      style={{
        background: 'var(--dag-node-human-bg)',
        border: '1px solid var(--dag-node-human-border)',
        borderRadius: '8px',
        padding: '8px 12px',
        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.08)',
      }}
    >
      <div className="flex items-center gap-2">
        <div
          className="flex items-center justify-center w-5 h-5 rounded-md flex-shrink-0"
          style={{
            background: 'var(--dag-node-human-border)',
            opacity: 0.3,
          }}
        >
          <span className="text-xs" style={{ color: 'var(--dag-node-human-text)' }}>👤</span>
        </div>
        <span className="text-xs font-medium truncate" style={{ color: 'var(--dag-node-human-text)' }}>
          {t('process.user')}
        </span>
      </div>
    </div>
  );
}

// ============================================================================
// AI Node — Blue (or Green for Final)
// ============================================================================

function AICard({ data }: { data: { type: 'ai'; modelName?: string | null; isFinal: boolean; toolCalls?: { name: string }[] | null; thinking?: string | null; thinkingStatus?: string | null } }) {
  const { t } = useI18n();
  const hasThinking = Boolean(data.thinking?.trim());
  const hasThinkingStatus = Boolean(data.thinkingStatus);
  const thinkingLabel = hasThinking
    ? t('process.thinking')
    : hasThinkingStatus
      ? t('process.noReasoningText')
      : null;
  // Use different colors for final vs non-final AI nodes
  const bgColor = data.isFinal ? 'var(--dag-node-final-bg)' : 'var(--dag-node-ai-bg)';
  const borderColor = data.isFinal ? 'var(--dag-node-final-border)' : 'var(--dag-node-ai-border)';
  const textColor = data.isFinal ? 'var(--dag-node-final-text)' : 'var(--dag-node-ai-text)';
  const Icon = hasThinking || hasThinkingStatus ? Brain : data.isFinal ? CheckCircle2 : Bot;

  return (
    <div
      style={{
        background: bgColor,
        border: `1px solid ${borderColor}`,
        borderRadius: '8px',
        padding: thinkingLabel ? '8px 10px' : '10px 14px',
        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.08)',
      }}
    >
      <div className="flex items-center justify-center gap-2">
        <Icon className="w-3.5 h-3.5 flex-shrink-0" style={{ color: textColor }} />
        <span className="text-xs font-medium" style={{ color: textColor }}>
          AI
        </span>
      </div>
      {thinkingLabel && (
        <div
          className="mt-1 text-[10px] leading-none text-center truncate"
          style={{ color: textColor, opacity: 0.82 }}
        >
          {thinkingLabel}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Tool Node — Purple
// ============================================================================

function ToolCard({ data, width }: { data: { type: 'tool'; toolName: string; toolOutput: string | null }; width: number }) {
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
    running: 'var(--dag-node-tool-text)',
    success: 'var(--dag-success)',
    error: 'var(--dag-error)',
  }[status];

  return (
    <div
      style={{
        background: 'var(--dag-node-tool-bg)',
        border: '1px solid var(--dag-node-tool-border)',
        borderRadius: '8px',
        padding: '8px 12px',
        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.08)',
        width: width,
        overflow: 'hidden',
      }}
    >
      <div className="flex items-center gap-2">
        <div
          className="flex items-center justify-center w-5 h-5 rounded-md flex-shrink-0"
          style={{
            background: 'var(--dag-node-tool-border)',
            opacity: 0.3,
          }}
        >
          <span className="text-xs">🔧</span>
        </div>
        <span className="text-xs font-medium" style={{ color: 'var(--dag-node-tool-text)' }}>
          {data.toolName}
        </span>
      </div>
      <div className="flex items-center gap-1.5 mt-1">
        <span className="text-xs" style={{ color: statusColor }}>{statusIcon}</span>
        <span className="text-xs" style={{ color: 'var(--dag-node-tool-text)', opacity: 0.7 }}>{statusText}</span>
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
