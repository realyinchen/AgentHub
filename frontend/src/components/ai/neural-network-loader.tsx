import { useI18n } from "@/i18n"
import { useTheme } from "@/hooks/use-theme"
import { cn } from "@/lib/utils"

export type SciFiLoaderProps = {
  className?: string
  showText?: boolean
}

/**
 * AI Agent Dashboard Loading animation.
 * Features: 3D atom orbits, multi-token streaming flow, rotating status messages.
 * Adapts colors for light/dark mode. All animations are pure CSS.
 */
export function SciFiLoader({
  className,
  showText = true,
}: SciFiLoaderProps) {
  const { t } = useI18n()
  const { theme } = useTheme()
  const isDark = theme === "dark"

  const colors = isDark
    ? {
      nucleusCore: "#00d4ff",
      nucleusGlow1: "#00eaff",
      nucleusGlow2: "#00aaff",
      nucleusGlow3: "rgba(0,170,255,0.5)",
      orbitBorder: "rgba(0,255,255,0.32)",
      orbitGlow: "rgba(0,255,255,0.15)",
      tokenBg: "#00f7ff",
      tokenGlow1: "#00f7ff",
      tokenGlow2: "#00c3ff",
      titleColor: "#8fbfff",
      statusColor: "#5f7fa3",
    }
    : {
      nucleusCore: "#008b9e",
      nucleusGlow1: "#009aab",
      nucleusGlow2: "#007a8a",
      nucleusGlow3: "rgba(0,120,140,0.4)",
      orbitBorder: "rgba(0,120,140,0.25)",
      orbitGlow: "rgba(0,120,140,0.1)",
      tokenBg: "#0099aa",
      tokenGlow1: "#0099aa",
      tokenGlow2: "#007788",
      titleColor: "#2a6888",
      statusColor: "#4a7a9a",
    }

  const statusMessages = [
    t("loader.status.analyzing"),
    t("loader.status.routing"),
    t("loader.status.reasoning"),
    t("loader.status.generating"),
  ]

  return (
    <div className={cn("flex flex-col items-center gap-[26px]", className)}>
      <div className="agent-atom" style={{ transformStyle: "preserve-3d" }}>
        <div className="agent-nucleus" />
        <div className="agent-orbit agent-orbit1">
          <span className="agent-token" />
          <span className="agent-token agent-d1" />
          <span className="agent-token agent-d2" />
        </div>
        <div className="agent-orbit agent-orbit2">
          <span className="agent-token" />
          <span className="agent-token agent-d1" />
        </div>
        <div className="agent-orbit agent-orbit3">
          <span className="agent-token" />
          <span className="agent-token agent-d2" />
        </div>
      </div>

      {showText && (
        <div className="agent-panel">
          <div className="agent-title">{t("loader.title")}</div>
          <div className="agent-status">
            {statusMessages.map((msg, i) => (
              <span
                key={i}
                className="agent-status-span"
                style={{ animationDelay: `${i * 2}s` }}
              >
                {msg}
              </span>
            ))}
          </div>
        </div>
      )}

      <style>{`
        .agent-atom {
          position: relative;
          width: 160px;
          height: 160px;
          transform-style: preserve-3d;
          animation: agentAtomSpin 14s linear infinite;
        }
        .agent-nucleus {
          position: absolute;
          top: 50%;
          left: 50%;
          width: 16px;
          height: 16px;
          transform: translate(-50%, -50%);
          border-radius: 50%;
          background: radial-gradient(circle, #b6fff9, ${colors.nucleusCore});
          box-shadow:
            0 0 15px ${colors.nucleusGlow1},
            0 0 40px ${colors.nucleusGlow2},
            0 0 70px ${colors.nucleusGlow3};
          animation: agentPulse 1.6s ease-in-out infinite alternate;
        }
        .agent-orbit {
          position: absolute;
          inset: 0;
          border-radius: 50%;
          border: 1px solid ${colors.orbitBorder};
          box-shadow:
            0 0 6px ${colors.orbitBorder},
            0 0 12px ${colors.orbitGlow};
        }
        .agent-orbit1 { transform: rotateX(70deg) scaleY(0.55); }
        .agent-orbit2 { transform: rotateY(70deg) scaleY(0.55); }
        .agent-orbit3 { transform: rotateX(70deg) rotateY(70deg) scaleY(0.55); }
        .agent-token {
          position: absolute;
          top: -5px;
          left: 50%;
          width: 8px;
          height: 8px;
          transform: translateX(-50%);
          border-radius: 50%;
          background: ${colors.tokenBg};
          box-shadow:
            0 0 8px ${colors.tokenGlow1},
            0 0 20px ${colors.tokenGlow2};
        }
        .agent-orbit1 .agent-token { animation: agentFlow 2.2s linear infinite; }
        .agent-orbit2 .agent-token { animation: agentFlow 3s linear infinite; }
        .agent-orbit3 .agent-token { animation: agentFlow 2.6s linear infinite; }
        .agent-d1 { animation-delay: 0.6s; }
        .agent-d2 { animation-delay: 1.2s; }
        @keyframes agentFlow {
          0% { transform: rotate(0deg) translateX(80px) rotate(0deg); opacity: 0; }
          10% { opacity: 1; }
          90% { opacity: 1; }
          100% { transform: rotate(360deg) translateX(80px) rotate(-360deg); opacity: 0; }
        }
        @keyframes agentPulse {
          from { transform: translate(-50%, -50%) scale(1); }
          to   { transform: translate(-50%, -50%) scale(1.35); }
        }
        @keyframes agentAtomSpin {
          from { transform: rotateX(0deg) rotateY(0deg); }
          to   { transform: rotateX(360deg) rotateY(360deg); }
        }
        .agent-panel { text-align: center; }
        .agent-title {
          font-size: 14px;
          letter-spacing: 1px;
          color: ${colors.titleColor};
        }
        .agent-status {
          position: relative;
          height: 18px;
          overflow: hidden;
          margin-top: 6px;
        }
        .agent-status-span {
          display: block;
          font-size: 12px;
          color: ${colors.statusColor};
          height: 18px;
          line-height: 18px;
          animation: agentStatusLoop 8s infinite;
        }
        @keyframes agentStatusLoop {
          0%   { opacity: 0; transform: translateY(10px); }
          10%  { opacity: 1; transform: translateY(0); }
          40%  { opacity: 1; }
          50%  { opacity: 0; transform: translateY(-10px); }
          100% { opacity: 0; }
        }
      `}</style>
    </div>
  )
}

export const NeuralNetworkLoader = SciFiLoader

export default function SciFiLoaderDemo() {
  const { theme, toggleTheme } = useTheme()

  return (
    <div
      className="flex flex-col items-center justify-center gap-12 p-8 min-h-screen"
      style={{ background: theme === "dark" ? "radial-gradient(circle at center, #0a0f1c, #02040a)" : "radial-gradient(circle at center, #f0f9ff, #e0f2fe 70%)" }}
    >
      <div className="flex flex-col items-center gap-4">
        <button
          onClick={toggleTheme}
          className="px-4 py-2 rounded-lg bg-muted hover:bg-muted/80"
        >
          Toggle Theme (Current: {theme})
        </button>
      </div>
      <div className="flex flex-col items-center gap-2">
        <SciFiLoader showText={true} />
        <span className="text-xs text-foreground/60">With status text</span>
      </div>
      <div className="flex flex-col items-center gap-2">
        <SciFiLoader showText={false} />
        <span className="text-xs text-foreground/60">Without status text</span>
      </div>
      <div className="flex flex-col items-center gap-2">
        <SciFiLoader className="w-24 h-24" showText={false} />
        <span className="text-xs text-foreground/60">Compact (w-24 h-24)</span>
      </div>
    </div>
  )
}