/**
 * BaseNode - Theme-aware rounded-rectangle node with glow border.
 * Icon + label/subtitle inside the node body.
 * All colors are CSS custom properties — adapts to light/dark themes.
 */

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { FlowNodeData, FlowNodeType } from '../hooks/useDAGFlow';
import { NODE_COLORS } from '../hooks/useDAGFlow';

// ============================================================================
// Icon mapping
// ============================================================================

import { User, Wrench, Cpu, Sparkles } from 'lucide-react';

const NODE_ICONS: Record<FlowNodeType, React.ComponentType<{ className?: string }>> = {
  'user': User,
  'tool': Wrench,
  'middle-ai': Cpu,
  'final-ai': Sparkles,
};

// ============================================================================
// Props
// ============================================================================

interface BaseNodeProps {
  data: FlowNodeData;
  selected?: boolean;
}

// ============================================================================
// Component
// ============================================================================

function BaseNode({ data, selected }: BaseNodeProps) {
  const colors = NODE_COLORS[data.type];
  const Icon = NODE_ICONS[data.type];

  // Glow uses the CSS variable directly — intensity varies by selection state
  const glowStyle = selected
    ? `0 0 12px ${colors.glow}, 0 0 30px ${colors.glow}, 0 0 60px color-mix(in srgb, ${colors.primary} 25%, transparent)`
    : `0 0 8px ${colors.glow}, 0 0 20px ${colors.glow}, 0 0 40px color-mix(in srgb, ${colors.primary} 13%, transparent)`;

  return (
    <div
      className="dag-node-wrapper"
      style={{
        cursor: 'pointer',
        userSelect: 'none',
      }}
    >
      {/* Invisible React Flow handles for edge routing */}
      <Handle
        type="target"
        position={Position.Top}
        style={{ opacity: 0, width: 1, height: 1 }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ opacity: 0, width: 1, height: 1 }}
      />

      {/* Rounded rectangle node body */}
      <div
        className="dag-node-rect"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '8px 14px',
          borderRadius: '12px',
          background: colors.bg,
          border: `2px solid ${colors.border}`,
          boxShadow: glowStyle,
          transition: 'box-shadow 0.3s ease, transform 0.2s ease',
          animation: 'dag-pulse 2s ease-in-out infinite',
          minWidth: '140px',
          maxWidth: '200px',
        }}
      >
        {/* Icon */}
        <span
          style={{
            color: colors.primary,
            filter: `drop-shadow(0 0 6px ${colors.glow})`,
            display: 'flex',
            flexShrink: 0,
          }}
        >
          <Icon className="size-5" />
        </span>

        {/* Text */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            minWidth: 0,
            overflow: 'hidden',
          }}
        >
          <span
            className="dag-node-label"
            style={{
              fontSize: '12px',
              fontWeight: 600,
              color: 'var(--dag-rf-node-label)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              lineHeight: 1.3,
            }}
          >
            {data.label}
          </span>
          <span
            className="dag-node-subtitle"
            style={{
              fontSize: '10px',
              color: 'var(--dag-rf-node-subtitle)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              lineHeight: 1.2,
            }}
          >
            {data.subtitle}
          </span>
        </div>
      </div>
    </div>
  );
}

export default memo(BaseNode);
