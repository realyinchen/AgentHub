import { HelpCircle, Flame } from "lucide-react"
import type { ConversationInDB } from "@/types"
import { useI18n } from "@/i18n"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

interface TokenStatsPanelProps {
  /** Current conversation with cumulative token stats */
  currentConversation: ConversationInDB | null
}

// Maximum token limit for the bar chart (128k)
const MAX_TOKENS = 128000

interface TokenBarProps {
  label: string
  value: number
  colorVar: string
  bgVar: string
  glowVar: string
  tooltip?: string
  percentage?: string
  isTotal?: boolean
}

function TokenBar({ label, value, colorVar, bgVar, glowVar, tooltip, percentage, isTotal }: TokenBarProps) {
  // Calculate fill ratio based on 128k max
  const ratio = Math.min((value / MAX_TOKENS) * 100, 100)

  return (
    <div className={cn("space-y-1.5", isTotal && "font-medium")}>
      <div className="flex justify-between items-center text-xs">
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <span className={cn(isTotal && "text-foreground")}>{label}</span>
          {tooltip && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <HelpCircle className="size-3 cursor-help opacity-60 hover:opacity-100 transition-opacity" />
                </TooltipTrigger>
                <TooltipContent
                  side="top"
                  className="text-xs bg-popover/95 backdrop-blur-sm border-border text-popover-foreground"
                >
                  {tooltip}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </div>
        <div className="flex items-center gap-1">
          <span className={cn("font-semibold text-foreground", isTotal && "text-base")}>
            {value.toLocaleString()}
          </span>
          {percentage && (
            <span className="text-[10px] text-muted-foreground/70">({percentage})</span>
          )}
        </div>
      </div>
      <div
        className={cn(
          "h-2 rounded-full overflow-hidden transition-all duration-200",
          isTotal && "h-2.5"
        )}
        style={{ backgroundColor: `var(${bgVar})` }}
      >
        <div
          className="h-full transition-all duration-500 ease-out rounded-full relative"
          style={{
            width: `${ratio}%`,
            backgroundColor: `var(${colorVar})`,
            boxShadow: ratio > 5 ? `var(${glowVar})` : 'none'
          }}
        >
          {/* Shimmer effect for non-empty bars */}
          {ratio > 10 && (
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-shimmer" />
          )}
        </div>
      </div>
    </div>
  )
}

export function TokenStatsPanel({ currentConversation }: TokenStatsPanelProps) {
  const { t } = useI18n()

  // Get cumulative tokens from conversation (or default to 0)
  const tokens = {
    input_tokens: currentConversation?.input_tokens ?? 0,
    cache_read: currentConversation?.cache_read ?? 0,
    output_tokens: currentConversation?.output_tokens ?? 0,
    reasoning: currentConversation?.reasoning ?? 0,
    total_tokens: currentConversation?.total_tokens ?? 0,
  }

  // Calculate total percentage for header indicator
  const totalPercentage = ((tokens.total_tokens / MAX_TOKENS) * 100).toFixed(1)
  const totalPercentageNum = parseFloat(totalPercentage)

  // Determine color based on percentage: normal (default), 80%+ warning (yellow), 90%+ danger (red)
  const getPercentageColorClass = () => {
    if (totalPercentageNum >= 90) return "text-red-500"
    if (totalPercentageNum >= 80) return "text-yellow-500"
    return "text-muted-foreground"
  }

  const getIndicatorColorClass = () => {
    if (totalPercentageNum >= 90) return "bg-red-500"
    if (totalPercentageNum >= 80) return "bg-yellow-500"
    return "bg-primary/50"
  }

  const percentageColorClass = getPercentageColorClass()
  const indicatorColorClass = getIndicatorColorClass()

  return (
    <div className="rounded-2xl bg-gradient-to-br from-muted/30 to-muted/50 
                    border border-border/50 overflow-hidden
                    backdrop-blur-sm shadow-lg">
      {/* Header */}
      <div className="p-3 flex items-center justify-between border-b border-border/30 bg-muted/20">
        <div className="flex items-center gap-2">
          <div
            className="size-7 rounded-lg flex items-center justify-center"
            style={{
              background: 'linear-gradient(135deg, var(--token-reasoning-bg), var(--token-total-bg))',
              boxShadow: 'var(--token-reasoning-glow)'
            }}
          >
            <Flame
              className="size-4"
              style={{ color: 'var(--token-reasoning)' }}
            />
          </div>
          <span className="text-sm font-semibold text-foreground">
            {t("token.title")}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={cn("text-xs font-medium", percentageColorClass)}>
            {totalPercentage}%
          </span>
          <div className={cn("size-1.5 rounded-full", indicatorColorClass)} />
          <span className="text-xs text-muted-foreground">
            128k
          </span>
        </div>
      </div>

      {/* Token bars */}
      <div className="p-3 space-y-3">
        {/* Input Tokens */}
        <TokenBar
          label={t("token.input")}
          value={tokens.input_tokens}
          colorVar="--token-input"
          bgVar="--token-track"
          glowVar="--token-input-glow"
          tooltip={t("token.inputTooltip")}
        />

        {/* Cache Read */}
        <TokenBar
          label={t("token.cacheRead") || "缓存"}
          value={tokens.cache_read}
          colorVar="--token-cache"
          bgVar="--token-track"
          glowVar="--token-cache-glow"
          tooltip={t("token.cacheReadTooltip")}
          percentage={
            tokens.input_tokens > 0
              ? `${((tokens.cache_read / tokens.input_tokens) * 100).toFixed(1)}%`
              : undefined
          }
        />

        {/* Output Tokens */}
        <TokenBar
          label={t("token.output")}
          value={tokens.output_tokens}
          colorVar="--token-output"
          bgVar="--token-track"
          glowVar="--token-output-glow"
        />

        {/* Reasoning Tokens */}
        <TokenBar
          label={t("token.reasoning")}
          value={tokens.reasoning}
          colorVar="--token-reasoning"
          bgVar="--token-track"
          glowVar="--token-reasoning-glow"
        />

        {/* Total */}
        <div className="pt-3 mt-3 border-t border-border/30">
          <TokenBar
            label={t("token.total")}
            value={tokens.total_tokens}
            colorVar="--token-total"
            bgVar="--token-track"
            glowVar="--token-total-glow"
            isTotal
          />
        </div>
      </div>
    </div>
  )
}
