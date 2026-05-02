/**
 * Kanban Dark Theme — Clean Dashboard Style
 *
 * Design principles:
 * - Single accent color per node type (no gradients, no glow)
 * - Flat card design with subtle borders
 * - Green edges for DAG connections
 * - Reference: Vercel Dashboard / Linear / Datadog
 */

export const DARK_THEME = {
  // ============================================================================
  // Background Hierarchy (unified dark theme)
  // ============================================================================
  bgMain: '#0B0F17',       // deepest — main background (same as sidebar)
  bgSidebar: '#0B0F17',    // unified with main (no blue tint)
  bgPanel: '#111826',      // panels / cards
  bgHover: '#1A2333',      // hover state

  // ============================================================================
  // Borders
  // ============================================================================
  border: 'rgba(255,255,255,0.06)',
  borderHover: 'rgba(255,255,255,0.10)',
  borderActive: 'rgba(91,140,255,0.3)',

  // ============================================================================
  // Text Hierarchy
  // ============================================================================
  textPrimary: '#E6EDF3',
  textSecondary: '#9FB0C3',
  textDim: '#6B7A90',

  // ============================================================================
  // Node Colors (clean, distinct per type)
  // ============================================================================
  nodeUser: '#9FB0C3',       // User — Gray (neutral, not decorative)
  nodeUserLight: 'rgba(159,176,195,0.10)',
  nodeUserBorder: 'rgba(159,176,195,0.3)',

  nodeAI: '#5B8CFF',         // AI — Blue
  nodeAILight: 'rgba(91,140,255,0.12)',
  nodeAIBorder: 'rgba(91,140,255,0.4)',

  nodeTool: '#A78BFA',       // Tool — Purple (reduced brightness)
  nodeToolLight: 'rgba(167,139,250,0.08)',
  nodeToolBorder: 'rgba(167,139,250,0.25)',

  // SubAgent gradient (blue to cyan)
  nodeSubagentFrom: '#5B8CFF',
  nodeSubagentTo: '#06B6D4',
  nodeSubagentLight: 'rgba(91,140,255,0.12)',

  // ============================================================================
  // Edge Color (green for all connections)
  // ============================================================================
  edgeColor: 'rgba(255,255,255,0.15)',
  edgeColorMuted: 'rgba(255,255,255,0.08)',

  // ============================================================================
  // Status Colors (semantic, not decorative)
  // ============================================================================
  success: '#22C55E',
  successLight: 'rgba(34,197,94,0.12)',
  successBorder: 'rgba(34,197,94,0.4)',

  warning: '#F59E0B',
  warningLight: 'rgba(245,158,11,0.12)',
  warningBorder: 'rgba(245,158,11,0.4)',

  error: '#EF4444',
  errorLight: 'rgba(239,68,68,0.12)',
  errorBorder: 'rgba(239,68,68,0.5)',

  // ============================================================================
  // Chart
  // ============================================================================
  chartPrimary: '#5B8CFF',
  chartSecondary: '#9FB0C3',
  chartGrid: 'rgba(255,255,255,0.04)',

  // ============================================================================
  // Shadows (flat, no glow)
  // ============================================================================
  shadow: '0 1px 3px rgba(0, 0, 0, 0.3)',
  shadowLg: '0 4px 12px rgba(0, 0, 0, 0.4)',
} as const;

// ============================================================================
// Legacy aliases (for backward compatibility during migration)
// ============================================================================
export const NODE_COLORS = {
  human: DARK_THEME.nodeUser,
  ai: DARK_THEME.nodeAI,
  tool: DARK_THEME.nodeTool,
  subagent: `${DARK_THEME.nodeSubagentFrom}`, // start of gradient
  final: DARK_THEME.success,
} as const;

/** @deprecated Use DARK_THEME.nodeUser etc. */
export const TOOL_COLOR_PALETTE = [
  DARK_THEME.nodeTool,   // amber (primary)
];

/** Get node border color by type */
export function getNodeBorderColor(type: 'human' | 'ai' | 'tool' | 'subagent' | 'final'): string {
  switch (type) {
    case 'human': return DARK_THEME.nodeUserBorder;
    case 'ai': return DARK_THEME.nodeAIBorder;
    case 'tool': return DARK_THEME.nodeToolBorder;
    case 'subagent': return DARK_THEME.nodeAIBorder; // gradient handled in CSS
    case 'final': return DARK_THEME.successBorder;
    default: return DARK_THEME.border;
  }
}

/** Get node icon background by type */
export function getNodeIconBg(type: 'human' | 'ai' | 'tool' | 'subagent' | 'final'): string {
  switch (type) {
    case 'human': return DARK_THEME.nodeUserLight;
    case 'ai': return DARK_THEME.nodeAILight;
    case 'tool': return DARK_THEME.nodeToolLight;
    case 'subagent': return DARK_THEME.nodeAILight;
    case 'final': return DARK_THEME.successLight;
    default: return 'rgba(255,255,255,0.04)';
  }
}

// ============================================================================
// Tailwind CSS Classes
// ============================================================================

export const TW_CLASSES = {
  card: 'bg-[#111826] border border-white/[0.06] rounded-xl',
  cardHover: 'hover:bg-[#1A2333] hover:border-white/[0.10]',
  textPrimary: 'text-[#E6EDF3]',
  textSecondary: 'text-[#9FB0C3]',
  textDim: 'text-[#6B7A90]',
  darkContainer: 'bg-[#0B0F17]',
  borderSubtle: 'border-white/[0.06]',
  nodeUser: 'border-[#9FB0C3]',
  nodeAI: 'border-[#5B8CFF]',
  nodeTool: 'border-[#A78BFA]',
  edge: 'stroke-white/15',
} as const;