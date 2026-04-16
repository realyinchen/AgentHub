import { useEffect, useRef, useCallback } from "react"
import { cn } from "@/lib/utils"
import { useI18n } from "@/i18n"

export type NeuralNetworkLoaderProps = {
  className?: string
  particleCount?: number
  maxDistance?: number
  showText?: boolean
}

/**
 * A premium Canvas-based particle neural network loading animation.
 * Features: particle floating, auto-connection, distance sensing, data flow, glow effects.
 * Performance optimized with requestAnimationFrame + distance culling.
 */
export function NeuralNetworkLoader({
  className,
  particleCount = 90,
  maxDistance = 120,
  showText = true,
}: NeuralNetworkLoaderProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const particlesRef = useRef<Particle[]>([])
  const animationRef = useRef<number | null>(null)
  const { t } = useI18n()

  // Particle class defined inside to access props
  class Particle {
    x: number
    y: number
    vx: number
    vy: number
    size: number
    canvasWidth: number
    canvasHeight: number

    constructor(canvasWidth: number, canvasHeight: number) {
      this.canvasWidth = canvasWidth
      this.canvasHeight = canvasHeight
      this.x = Math.random() * canvasWidth
      this.y = Math.random() * canvasHeight
      this.vx = (Math.random() - 0.5) * 0.6
      this.vy = (Math.random() - 0.5) * 0.6
      this.size = Math.random() * 2 + 1
    }

    move() {
      this.x += this.vx
      this.y += this.vy

      // Bounce off edges
      if (this.x < 0 || this.x > this.canvasWidth) this.vx *= -1
      if (this.y < 0 || this.y > this.canvasHeight) this.vy *= -1
    }
  }

  const initParticles = useCallback((canvas: HTMLCanvasElement) => {
    particlesRef.current = []
    for (let i = 0; i < particleCount; i++) {
      particlesRef.current.push(new Particle(canvas.width, canvas.height))
    }
  }, [particleCount])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Handle resize
    const handleResize = () => {
      const container = canvas.parentElement
      if (container) {
        canvas.width = container.clientWidth
        canvas.height = container.clientHeight
        // Re-initialize particles on resize
        initParticles(canvas)
      }
    }

    handleResize()
    window.addEventListener('resize', handleResize)

    // Initialize particles
    initParticles(canvas)

    // Animation loop
    const animate = () => {
      if (!ctx || !canvas) return

      ctx.clearRect(0, 0, canvas.width, canvas.height)

      const particles = particlesRef.current

      // Update and draw particles
      particles.forEach(p => {
        p.canvasWidth = canvas.width
        p.canvasHeight = canvas.height
        p.move()

        // Draw particle with glow
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2)
        ctx.fillStyle = '#00f7ff'
        ctx.shadowColor = '#00f7ff'
        ctx.shadowBlur = 8
        ctx.fill()
        ctx.shadowBlur = 0
      })

      // Draw connections
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x
          const dy = particles[i].y - particles[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)

          if (dist < maxDistance) {
            const opacity = 1 - dist / maxDistance

            // Draw connection line
            ctx.beginPath()
            ctx.moveTo(particles[i].x, particles[i].y)
            ctx.lineTo(particles[j].x, particles[j].y)
            ctx.strokeStyle = `rgba(0, 247, 255, ${opacity * 0.6})`
            ctx.lineWidth = 1
            ctx.stroke()

            // Data flow effect - moving highlight along the line
            const t = (Date.now() * 0.002) % 1
            const flowX = particles[i].x + (particles[j].x - particles[i].x) * t
            const flowY = particles[i].y + (particles[j].y - particles[i].y) * t

            ctx.beginPath()
            ctx.arc(flowX, flowY, 2, 0, Math.PI * 2)
            ctx.fillStyle = '#ffffff'
            ctx.shadowColor = '#00f7ff'
            ctx.shadowBlur = 10
            ctx.fill()
            ctx.shadowBlur = 0
          }
        }
      }

      animationRef.current = requestAnimationFrame(animate)
    }

    animate()

    return () => {
      window.removeEventListener('resize', handleResize)
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [initParticles, maxDistance])

  return (
    <div className={cn("relative w-full min-h-[120px] h-full overflow-hidden", className)}>
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full"
        style={{ background: 'radial-gradient(circle at center, #020617, #000)' }}
      />
      
      {/* Loading text overlay */}
      {showText && (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-sm text-cyan-400/80 animate-pulse drop-shadow-[0_0_8px_rgba(0,247,255,0.5)]">
            {t("loader.title")}
          </span>
        </div>
      )}
    </div>
  )
}

/** Demo component for preview */
export default function NeuralNetworkLoaderDemo() {
  return (
    <div className="flex flex-col items-center justify-center gap-8 p-8">
      <div className="flex flex-col items-center gap-2">
        <NeuralNetworkLoader particleCount={60} showText={false} />
        <span className="text-xs text-muted-foreground">Fewer particles</span>
      </div>
      <div className="flex flex-col items-center gap-2">
        <NeuralNetworkLoader showText={false} />
        <span className="text-xs text-muted-foreground">Default (90 particles)</span>
      </div>
      <div className="flex flex-col items-center gap-2">
        <NeuralNetworkLoader particleCount={120} maxDistance={150} showText={true} />
        <span className="text-xs text-muted-foreground">Dense network</span>
      </div>
    </div>
  )
}
