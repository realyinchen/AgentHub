import { cn } from "@/lib/utils"
import { useI18n } from "@/i18n"

export type SciFiLoaderProps = {
  className?: string
  size?: "sm" | "md" | "lg"
  showText?: boolean
}

/**
 * A sci-fi themed loading animation with pulsing rings and orbiting particles.
 * Perfect for AI processing states.
 */
export function SciFiLoader({ 
  className, 
  size = "md",
  showText = true 
}: SciFiLoaderProps) {
  const { t } = useI18n()
  
  const sizeClasses = {
    sm: "w-12 h-12",
    md: "w-20 h-20",
    lg: "w-32 h-32"
  }
  
  const particleSizes = {
    sm: "w-1 h-1",
    md: "w-1.5 h-1.5",
    lg: "w-2 h-2"
  }

  return (
    <div className={cn("flex flex-col items-center gap-3 p-4 bg-ai-bubble rounded-2xl", className)}>
      {/* Main loader container */}
      <div className={cn("relative", sizeClasses[size])}>
        {/* Core glow */}
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-1/3 h-1/3 rounded-full bg-primary/30 animate-pulse" />
        </div>
        
        {/* Inner ring - fast spin */}
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: "2s" }}>
          <div className="absolute inset-1 rounded-full border border-primary/40" />
        </div>
        
        {/* Middle ring - medium spin, opposite direction */}
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: "3s", animationDirection: "reverse" }}>
          <div className="absolute inset-2 rounded-full border border-dashed border-cyan-400/30" />
        </div>
        
        {/* Outer ring - slow spin */}
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: "5s" }}>
          <div className="absolute inset-0 rounded-full border border-blue-500/20" />
        </div>
        
        {/* Pulsing ring effect */}
        <div className="absolute inset-0">
          <div className="absolute inset-0 rounded-full border-2 border-primary/20 animate-ping" style={{ animationDuration: "2s" }} />
        </div>
        
        {/* Orbiting particles */}
        {/* Particle 1 - top */}
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: "1.5s" }}>
          <div 
            className={cn(
              "absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan-400 shadow-lg shadow-cyan-400/50",
              particleSizes[size]
            )} 
          />
        </div>
        
        {/* Particle 2 - bottom right */}
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: "1.5s", animationDelay: "-0.5s" }}>
          <div 
            className={cn(
              "absolute bottom-0 right-0 translate-x-1/2 translate-y-1/2 rounded-full bg-blue-500 shadow-lg shadow-blue-500/50",
              particleSizes[size]
            )} 
          />
        </div>
        
        {/* Particle 3 - bottom left */}
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: "1.5s", animationDelay: "-1s" }}>
          <div 
            className={cn(
              "absolute bottom-0 left-0 -translate-x-1/2 translate-y-1/2 rounded-full bg-purple-400 shadow-lg shadow-purple-400/50",
              particleSizes[size]
            )} 
          />
        </div>
        
        {/* Secondary orbiting particles - slower */}
        {/* Particle 4 */}
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: "2.5s", animationDirection: "reverse" }}>
          <div 
            className={cn(
              "absolute top-1/4 right-0 translate-x-1/2 rounded-full bg-primary/60 shadow-lg shadow-primary/30",
              particleSizes[size]
            )} 
          />
        </div>
        
        {/* Particle 5 */}
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: "2.5s", animationDelay: "-0.8s", animationDirection: "reverse" }}>
          <div 
            className={cn(
              "absolute bottom-1/4 left-0 -translate-x-1/2 rounded-full bg-indigo-400/60 shadow-lg shadow-indigo-400/30",
              particleSizes[size]
            )} 
          />
        </div>
        
        {/* Center dot with glow */}
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-2 h-2 rounded-full bg-white shadow-lg shadow-white/50 animate-pulse" />
        </div>
        
        {/* Scan line effect */}
        <div className="absolute inset-0 overflow-hidden rounded-full">
          <div 
            className="absolute inset-x-0 h-1/2 bg-gradient-to-b from-transparent via-primary/5 to-transparent animate-scan"
          />
        </div>
      </div>
      
      {/* Loading text with animated dots */}
      {showText && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>{t("message.processing")}</span>
          <span className="inline-flex gap-0.5">
            <span className="w-1 h-1 rounded-full bg-current animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-1 h-1 rounded-full bg-current animate-bounce" style={{ animationDelay: "150ms" }} />
            <span className="w-1 h-1 rounded-full bg-current animate-bounce" style={{ animationDelay: "300ms" }} />
          </span>
        </div>
      )}
    </div>
  )
}

/** Demo component for preview */
export default function SciFiLoaderDemo() {
  return (
    <div className="flex flex-col items-center justify-center gap-8 p-8 bg-background">
      <div className="flex items-center gap-8">
        <div className="flex flex-col items-center gap-2">
          <SciFiLoader size="sm" showText={false} />
          <span className="text-xs text-muted-foreground">Small</span>
        </div>
        <div className="flex flex-col items-center gap-2">
          <SciFiLoader size="md" showText={false} />
          <span className="text-xs text-muted-foreground">Medium</span>
        </div>
        <div className="flex flex-col items-center gap-2">
          <SciFiLoader size="lg" showText={false} />
          <span className="text-xs text-muted-foreground">Large</span>
        </div>
      </div>
      <SciFiLoader size="md" showText={true} />
    </div>
  )
}