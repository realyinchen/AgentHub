import { useMemo } from "react"
import { User, Bot, Brain, HelpCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { useI18n } from "@/i18n"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface TokenStatsProps {
  userTokens: number
  aiTokens: number
  reasoningTokens: number
  className?: string
}

export function TokenStats({ userTokens, aiTokens, reasoningTokens, className }: TokenStatsProps) {
  const { t } = useI18n()
  const totalTokens = userTokens + aiTokens + reasoningTokens
  
  // Calculate bar heights (percentage of total)
  const userPercent = totalTokens > 0 ? (userTokens / totalTokens) * 100 : 0
  const aiPercent = totalTokens > 0 ? (aiTokens / totalTokens) * 100 : 0
  const reasoningPercent = totalTokens > 0 ? (reasoningTokens / totalTokens) * 100 : 0

  // Format numbers for display
  const formatTokens = (num: number): string => {
    if (num >= 1000000) {
      return `${(num / 1000000).toFixed(1)}M`
    }
    if (num >= 1000) {
      return `${(num / 1000).toFixed(1)}K`
    }
    return num.toString()
  }

  const stats = useMemo(() => [
    {
      key: "input",
      label: t("token.input"),
      value: userTokens,
      percent: userPercent,
      icon: User,
      color: "bg-blue-500",
      hasHint: true,
    },
    {
      key: "output",
      label: t("token.output"),
      value: aiTokens,
      percent: aiPercent,
      icon: Bot,
      color: "bg-green-500",
      hasHint: false,
    },
    {
      key: "reasoning",
      label: t("token.reasoning"),
      value: reasoningTokens,
      percent: reasoningPercent,
      icon: Brain,
      color: "bg-purple-500",
      hasHint: false,
    },
  ], [userTokens, aiTokens, reasoningTokens, userPercent, aiPercent, reasoningPercent, t])

  return (
    <TooltipProvider>
      <div className={cn("mt-auto pt-4 space-y-4", className)}>
        {/* Vertical bar chart */}
        <div className="flex items-end justify-center gap-6 h-40 px-2">
          {stats.map((stat) => (
            <div key={stat.key} className="flex flex-col items-center gap-2 w-16">
              {/* Vertical bar container */}
              <div className="w-8 h-32 bg-border/50 rounded-sm overflow-hidden flex flex-col justify-end">
                <div 
                  className={cn("w-full transition-all duration-300 rounded-t-sm", stat.color)}
                  style={{ height: `${stat.percent}%` }}
                />
              </div>
              {/* Icon */}
              <stat.icon className="size-4 text-muted-foreground" />
              {/* Label with hint */}
              <div className="flex items-center gap-0.5">
                <span className="text-xs font-medium text-muted-foreground">{stat.label}</span>
                {stat.hasHint && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <HelpCircle className="size-3 text-muted-foreground cursor-help" />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="text-xs">
                      {t("token.inputHint")}
                    </TooltipContent>
                  </Tooltip>
                )}
              </div>
              {/* Value */}
              <span className="text-xs text-muted-foreground">
                {formatTokens(stat.value)}
              </span>
            </div>
          ))}
        </div>

        {/* Total */}
        <div className="text-center text-xs text-muted-foreground">
          {t("token.total")}: {formatTokens(totalTokens)} tokens
        </div>
      </div>
    </TooltipProvider>
  )
}