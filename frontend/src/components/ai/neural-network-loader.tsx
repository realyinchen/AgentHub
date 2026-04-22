import { useEffect, useRef, useCallback, useState } from "react"
import { cn } from "@/lib/utils"
import { useI18n } from "@/i18n"
import { useTheme } from "@/hooks/use-theme"

export type SciFiLoaderProps = {
  className?: string
  showText?: boolean
  /** Cell size in pixels - default 14, auto-calculated from container if not provided */
  cellSize?: number
  /** Gap between cells in pixels - default 5 */
  gap?: number
  /** Animation duration in seconds - default 2.2 */
  animationDuration?: number
}

interface CellData {
  x: number
  y: number
  dist: number
  delay: number
  isCenter: boolean
}

/**
 * A CSS Grid-based AI pulse wave animation loader.
 * Features: 3D perspective grid, heartbeat pulse animation, wave propagation from center.
 * Adapts colors for light/dark mode: darker cyan for light mode, bright cyan for dark mode.
 * Grid size is automatically calculated based on container size.
 */
export function SciFiLoader({
  className,
  showText = true,
  cellSize: providedCellSize,
  gap = 5,
  animationDuration = 2.2,
}: SciFiLoaderProps) {
  const { t } = useI18n()
  const { theme } = useTheme()
  const containerRef = useRef<HTMLDivElement>(null)
  const [cells, setCells] = useState<CellData[]>([])
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })

  // Determine if we're in dark mode
  const isDark = theme === "dark"

  // Calculate cell size and grid size based on container
  const calculateGrid = useCallback(() => {
    const container = containerRef.current
    if (!container || dimensions.width === 0 || dimensions.height === 0) {
      return { cellSize: 14, gridSize: 21 }
    }

    const containerSize = Math.min(dimensions.width, dimensions.height)

    // If cellSize is provided, use it; otherwise calculate based on container
    let actualCellSize: number
    if (providedCellSize) {
      actualCellSize = providedCellSize
    } else {
      // Calculate cell size to fit approximately 21 cells in smaller dimension
      // But cap it so it doesn't get too big or too small
      actualCellSize = Math.max(8, Math.min(14, containerSize / 22))
    }

    // Calculate grid size (number of cells per row/column)
    const gridSize = Math.max(5, Math.floor((containerSize + gap) / (actualCellSize + gap)))

    return { cellSize: actualCellSize, gridSize }
  }, [dimensions, providedCellSize, gap])

  const { cellSize, gridSize } = calculateGrid()
  const totalSize = gridSize * cellSize + (gridSize - 1) * gap

  // Generate cell data based on grid size
  const generateCells = useCallback(() => {
    const newCells: CellData[] = []
    const center = Math.floor(gridSize / 2)

    for (let y = 0; y < gridSize; y++) {
      for (let x = 0; x < gridSize; x++) {
        const dx = x - center
        const dy = y - center
        const dist = Math.sqrt(dx * dx + dy * dy)
        const delay = dist * 0.08

        newCells.push({
          x,
          y,
          dist,
          delay,
          isCenter: x === center && y === center,
        })
      }
    }

    setCells(newCells)
  }, [gridSize])

  useEffect(() => {
    generateCells()
  }, [generateCells])

  // Observe container size changes
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        setDimensions({ width, height })
      }
    })

    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
    }
  }, [])

  // Color palette based on theme
  // Dark mode: bright cyan (#00ffff)
  // Light mode: darker cyan (#006b6b) for sci-fi effect
  const colors = isDark
    ? {
      bgBase: "rgba(0, 255, 255, 0.05)",
      borderBase: "rgba(0, 255, 255, 0.08)",
      bg0: "rgba(0, 255, 255, 0.03)",
      bg20: "rgba(0, 255, 255, 0.15)",
      bg40: "rgba(0, 255, 255, 0.8)",
      bg70: "rgba(0, 255, 255, 0.1)",
      shadow0: "rgba(0, 255, 255, 0)",
      shadow20: "rgba(0, 255, 255, 0.5)",
      shadow40: "rgba(0, 255, 255, 0.9)",
      shadow70: "rgba(0, 255, 255, 0.2)",
      center: "rgba(0, 255, 255, 1)",
      centerShadow: "rgba(0, 255, 255, 1)",
    }
    : {
      // Light mode: darker cyan for visibility
      bgBase: "rgba(0, 107, 107, 0.1)",
      borderBase: "rgba(0, 107, 107, 0.15)",
      bg0: "rgba(0, 107, 107, 0.05)",
      bg20: "rgba(0, 107, 107, 0.25)",
      bg40: "rgba(0, 107, 107, 0.6)",
      bg70: "rgba(0, 107, 107, 0.2)",
      shadow0: "rgba(0, 107, 107, 0)",
      shadow20: "rgba(0, 107, 107, 0.4)",
      shadow40: "rgba(0, 107, 107, 0.7)",
      shadow70: "rgba(0, 107, 107, 0.2)",
      center: "rgba(0, 80, 80, 1)",
      centerShadow: "rgba(0, 80, 80, 0.8)",
    }

  return (
    <div className={cn("flex flex-col items-center justify-center", className)}>
      <div
        ref={containerRef}
        className="relative flex items-center justify-center"
        style={{
          width: "100%",
          height: "100%",
          minWidth: `${totalSize}px`,
          minHeight: `${totalSize}px`,
        }}
      >
        <div
          className="grid"
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${gridSize}, ${cellSize}px)`,
            gridTemplateRows: `repeat(${gridSize}, ${cellSize}px)`,
            gap: `${gap}px`,
            transform: "perspective(800px) rotateX(55deg)",
            transformStyle: "preserve-3d",
          }}
        >
          {cells.map((cell, index) => (
            <div
              key={index}
              className={cell.isCenter ? "scifi-cell scifi-cell-center" : "scifi-cell"}
              style={{
                width: cellSize,
                height: cellSize,
                animationDelay: `${cell.delay}s`,
                animationDuration: `${animationDuration}s`,
              }}
            />
          ))}
        </div>

        <style>{`
          .scifi-cell {
            background: ${colors.bgBase};
            border: 1px solid ${colors.borderBase};
            transform: scale(1);
            animation: scifi-pulse 2.2s infinite;
            will-change: transform, background, box-shadow;
          }

          .scifi-cell-center {
            background: ${colors.center} !important;
            box-shadow: 0 0 25px ${colors.centerShadow} !important;
          }

          @keyframes scifi-pulse {
            0% {
              background: ${colors.bg0};
              box-shadow: 0 0 0 ${colors.shadow0};
              transform: scale(1);
            }
            20% {
              background: ${colors.bg20};
              box-shadow: 0 0 8px ${colors.shadow20};
            }
            40% {
              background: ${colors.bg40};
              box-shadow: 0 0 18px ${colors.shadow40};
              transform: scale(1.25);
            }
            70% {
              background: ${colors.bg70};
              box-shadow: 0 0 5px ${colors.shadow70};
              transform: scale(1);
            }
            100% {
              background: ${colors.bg0};
              box-shadow: 0 0 0 ${colors.shadow0};
            }
          }
        `}</style>
      </div>
      {showText && (
        <span className={cn(
          "text-sm animate-pulse mt-2",
          isDark ? "text-cyan-400/80" : "text-cyan-700/80"
        )}>
          {t("loader.title")}
        </span>
      )}
    </div>
  )
}

// Keep backward compatibility alias
export const NeuralNetworkLoader = SciFiLoader

/** Demo component for preview */
export default function SciFiLoaderDemo() {
  const { theme, toggleTheme } = useTheme()

  return (
    <div
      className="flex flex-col items-center justify-center gap-12 p-8 min-h-screen"
      style={{ background: theme === "dark" ? "radial-gradient(circle at center, #050b12, #02040a 70%)" : "radial-gradient(circle at center, #f0f9ff, #e0f2fe 70%)" }}
    >
      <div className="flex flex-col items-center gap-4">
        <button
          onClick={toggleTheme}
          className="px-4 py-2 rounded-lg bg-muted hover:bg-muted/80"
        >
          Toggle Theme (Current: {theme})
        </button>
      </div>
      <div className="flex flex-col items-center gap-2 w-[300px] h-[200px]">
        <SciFiLoader showText={false} />
        <span className="text-xs text-foreground/60">Adaptive (auto-calculated)</span>
      </div>
      <div className="flex flex-col items-center gap-2 w-[300px] h-[200px]">
        <SciFiLoader showText={true} cellSize={10} />
        <span className="text-xs text-foreground/60">Fixed cell size (10px)</span>
      </div>
    </div>
  )
}
