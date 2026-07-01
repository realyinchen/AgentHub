/**
 * GlowEdge - Theme-aware bezier edge with gradient glow.
 * Resolves CSS custom properties at render time so SVG gradient stops
 * and marker fills get real color values.
 * Subscribes to <html> class changes for theme reactivity.
 */

import { memo, useEffect, useState, useCallback } from 'react';
import {
  BaseEdge,
  getBezierPath,
  type EdgeProps,
} from '@xyflow/react';

// ============================================================================
// Resolve a CSS custom property to its computed value
// ============================================================================

function resolveCSSVar(varRef: string): string {
  if (typeof document === 'undefined') return '#3B82F6';
  const name = varRef.replace(/^var\(|\)$/g, '').trim();
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || '#3B82F6';
}

// ============================================================================
// Hook: subscribes to theme changes (dark class toggle on <html>)
// ============================================================================

function useResolvedColors(sourceVar: string, targetVar: string) {
  const resolve = useCallback(() => ({
    source: resolveCSSVar(sourceVar),
    target: resolveCSSVar(targetVar),
  }), [sourceVar, targetVar]);

  const [colors, setColors] = useState(resolve);

  useEffect(() => {
    // Re-resolve on mount
    setColors(resolve());

    // Watch for class changes on <html> (theme toggle adds/removes .dark)
    const observer = new MutationObserver(() => {
      setColors(resolve());
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, [resolve]);

  return colors;
}

// ============================================================================
// Props
// ============================================================================

interface GlowEdgeData {
  sourceColor?: string;
  targetColor?: string;
}

function GlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: EdgeProps) {
  const edgeData = (data ?? {}) as GlowEdgeData;
  const sourceVar = edgeData.sourceColor ?? 'var(--dag-node-ai-border)';
  const targetVar = edgeData.targetColor ?? 'var(--dag-node-final-border)';

  // Resolve CSS variables → actual hex/rgb colors for SVG attributes
  const { source: sourceColor, target: targetColor } = useResolvedColors(sourceVar, targetVar);

  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  // Unique IDs per edge to avoid SVG ID collisions
  const gradientId = `glow-gradient-${id}`;
  const glowFilterId = `glow-filter-${id}`;
  const glowFilterSelectedId = `glow-filter-selected-${id}`;
  const markerId = `arrow-${id}`;

  const strokeColor = selected ? 'var(--dag-rf-node-label)' : `url(#${gradientId})`;
  const strokeWidth = selected ? 2.5 : 1.5;
  const glowFilter = selected ? `url(#${glowFilterSelectedId})` : `url(#${glowFilterId})`;

  return (
    <>
      {/* SVG definitions */}
      <defs>
        {/* Gradient: source color → target color */}
        <linearGradient id={gradientId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={sourceColor} stopOpacity={0.9} />
          <stop offset="50%" stopColor={sourceColor} stopOpacity={0.7}>
            <animate
              attributeName="stop-opacity"
              values="0.7;0.4;0.7"
              dur="2s"
              repeatCount="indefinite"
            />
          </stop>
          <stop offset="100%" stopColor={targetColor} stopOpacity={0.9} />
        </linearGradient>

        {/* Arrow marker */}
        <marker
          id={markerId}
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path
            d="M 0 0 L 10 5 L 0 10 z"
            fill={targetColor}
            opacity={0.85}
          />
        </marker>

        {/* Glow filter */}
        <filter id={glowFilterId} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        {/* Selected glow filter (brighter) */}
        <filter id={glowFilterSelectedId} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Main edge path */}
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={`url(#${markerId})`}
        style={{
          stroke: strokeColor,
          strokeWidth,
          fill: 'none',
          filter: glowFilter,
          transition: 'stroke 0.3s ease, stroke-width 0.3s ease',
        }}
      />

      {/* Animated dash overlay for flowing light effect */}
      <path
        d={edgePath}
        fill="none"
        stroke={sourceColor}
        strokeWidth={1}
        strokeDasharray="4 8"
        strokeOpacity={0.5}
        markerEnd={`url(#${markerId})`}
        style={{
          animation: 'dag-flow 1.5s linear infinite',
        }}
      />
    </>
  );
}

export default memo(GlowEdge);
