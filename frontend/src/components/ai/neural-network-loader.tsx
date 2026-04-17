import { useEffect, useRef, useCallback } from "react"
import { cn } from "@/lib/utils"
import { useI18n } from "@/i18n"

export type SciFiLoaderProps = {
  className?: string
  showText?: boolean
  /** Particle count - default 50, range 30-100 recommended */
  particleCount?: number
  /** Max connection distance - default 80, larger = denser connections */
  maxDistance?: number
}

/**
 * A Canvas-based neural network particle animation loader.
 * Features: floating particles, auto-connecting lines, distance sensing, data flow, glow effects.
 */
export function SciFiLoader({
  className,
  showText = true,
  particleCount = 50,
  maxDistance = 80,
}: SciFiLoaderProps) {
  const { t } = useI18n()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationRef = useRef<number | null>(null)
  const particlesRef = useRef<Particle[]>([])

  // Particle class defined inside component to access canvas ref
  class Particle {
    x: number
    y: number
    vx: number
    vy: number
    size: number

    constructor(canvas: HTMLCanvasElement) {
      this.x = Math.random() * canvas.width
      this.y = Math.random() * canvas.height
      this.vx = (Math.random() - 0.5) * 0.5
      this.vy = (Math.random() - 0.5) * 0.5
      this.size = Math.random() * 1.5 + 0.8
    }

    move(canvas: HTMLCanvasElement) {
      this.x += this.vx
      this.y += this.vy

      // Boundary bounce
      if (this.x < 0 || this.x > canvas.width) this.vx *= -1
      if (this.y < 0 || this.y > canvas.height) this.vy *= -1
    }

    draw(ctx: CanvasRenderingContext2D) {
      ctx.beginPath()
      ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2)
      ctx.fillStyle = "#00f7ff"
      ctx.shadowColor = "#00f7ff"
      ctx.shadowBlur = 6
      ctx.fill()
    }
  }

  const init = useCallback((canvas: HTMLCanvasElement) => {
    particlesRef.current = []
    for (let i = 0; i < particleCount; i++) {
      particlesRef.current.push(new Particle(canvas))
    }
  }, [particleCount])

  const connect = useCallback((ctx: CanvasRenderingContext2D, particles: Particle[]) => {
    const now = Date.now()

    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x
        const dy = particles[i].y - particles[j].y
        const dist = Math.sqrt(dx * dx + dy * dy)

        if (dist < maxDistance) {
          const opacity = 1 - dist / maxDistance

          ctx.beginPath()
          ctx.moveTo(particles[i].x, particles[i].y)
          ctx.lineTo(particles[j].x, particles[j].y)
          ctx.strokeStyle = `rgba(0,247,255,${opacity * 0.5})`
          ctx.lineWidth = 0.8
          ctx.shadowBlur = 0
          ctx.stroke()

          // Data flow effect - moving highlight along the line
          const t = (now * 0.002) % 1
          const x = particles[i].x + (particles[j].x - particles[i].x) * t
          const y = particles[i].y + (particles[j].y - particles[i].y) * t

          ctx.beginPath()
          ctx.arc(x, y, 1.2, 0, Math.PI * 2)
          ctx.fillStyle = "#ffffff"
          ctx.shadowColor = "#ffffff"
          ctx.shadowBlur = 4
          ctx.fill()
        }
      }
    }
  }, [maxDistance])

  const animate = useCallback(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext("2d")
    if (!canvas || !ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    // Reset shadow for particles
    ctx.shadowBlur = 6
    ctx.shadowColor = "#00f7ff"

    particlesRef.current.forEach((p) => {
      p.move(canvas)
      p.draw(ctx)
    })

    connect(ctx, particlesRef.current)

    animationRef.current = requestAnimationFrame(animate)
  }, [connect])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    // Set canvas size
    const resize = () => {
      const container = canvas.parentElement
      if (container) {
        const rect = container.getBoundingClientRect()
        canvas.width = rect.width
        canvas.height = rect.height
      }
    }

    resize()
    init(canvas)
    animate()

    // Handle resize with ResizeObserver for better container size detection
    const resizeObserver = new ResizeObserver(() => {
      resize()
      if (canvas) init(canvas)
    })

    const container = canvas.parentElement
    if (container) {
      resizeObserver.observe(container)
    }

    return () => {
      resizeObserver.disconnect()
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [animate, init])

  return (
    <div className={cn("flex flex-col items-center justify-center", className)}>
      <div className="relative w-full h-full">
        <canvas
          ref={canvasRef}
          className="block w-full h-full"
        />
      </div>
      {showText && (
        <span className="text-sm text-cyan-400/80 animate-pulse mt-2">
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
  return (
    <div
      className="flex flex-col items-center justify-center gap-12 p-8 min-h-screen"
      style={{ background: "radial-gradient(circle at center, #020617, #000)" }}
    >
      <div className="flex flex-col items-center gap-2 w-[300px] h-[200px]">
        <SciFiLoader showText={false} />
        <span className="text-xs text-cyan-400/60">AI Loader</span>
      </div>
      <div className="flex flex-col items-center gap-2 w-[300px] h-[200px]">
        <SciFiLoader showText={true} />
        <span className="text-xs text-cyan-400/60">With Text</span>
      </div>
    </div>
  )
}