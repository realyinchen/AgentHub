import { cn } from "@/lib/utils"

interface AgentHubLogoProps {
  className?: string
  size?: "sm" | "md" | "lg"
}

export function AgentHubLogo({ className, size = "md" }: AgentHubLogoProps) {
  const sizeClasses = {
    sm: "text-xl",
    md: "text-3xl",
    lg: "text-5xl",
  }

  const hubPadding = {
    sm: "px-2 py-1",
    md: "px-4 py-1.5",
    lg: "px-6 py-2",
  }

  return (
    <span className={cn("flex items-center font-black select-none", sizeClasses[size], className)} style={{ letterSpacing: "-0.02em" }}>
      <span className="text-gray-900 dark:text-white">Agent</span>
      <span className="relative" style={{ marginLeft: "0.25em" }}>
        <span
          className={cn(
            "inline-block text-white dark:text-black",
            hubPadding[size]
          )}
          style={{
            backgroundColor: "#f9a825",
            borderRadius: "12px",
            lineHeight: 1,
            boxShadow: `
              inset 0 2px 0 rgba(255, 255, 255, 0.25),
              0 4px 12px rgba(0, 0, 0, 0.4)
            `,
          }}
        >
          Hub
        </span>
        {/* Glossy overlay effect */}
        <span
          className="absolute inset-0 pointer-events-none"
          style={{
            borderRadius: "12px",
            background: "linear-gradient(to bottom, rgba(255,255,255,0.25), rgba(255,255,255,0))",
          }}
        />
      </span>
    </span>
  )
}
