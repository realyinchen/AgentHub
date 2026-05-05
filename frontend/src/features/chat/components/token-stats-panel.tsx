import { useState, useEffect, useCallback } from "react"
import { HelpCircle, Activity } from "lucide-react"
import type { ConversationInDB } from "@/types"
import { useI18n } from "@/i18n"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts"

interface TokenStatsPanelProps {
  /** Current conversation with cumulative token stats */
  currentConversation: ConversationInDB | null
}

// Maximum token limit for the bar chart (128k)
const MAX_TOKENS = 128000

type DailyStat = {
  date: string
  count: number
  total_tokens: number
  input_tokens: number
  output_tokens: number
  reasoning: number
  cache_read: number
}

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

// Format number for chart
const formatNumber = (num: number): string => {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + "M"
  if (num >= 1000) return (num / 1000).toFixed(1) + "K"
  return num.toString()
}

// Format date for chart
const formatDate = (dateStr: string): string => {
  const date = new Date(dateStr)
  return `${date.getMonth() + 1}/${date.getDate()}`
}

// Custom tooltip for stacked bar chart
function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: any[]; label?: string }) {
  const { t } = useI18n()
  
  if (active && payload && payload.length) {
    const data = payload[0].payload
    return (
      <div className="rounded-lg px-3 py-2 text-xs bg-popover/95 backdrop-blur-sm border border-border shadow-lg">
        <p className="font-medium mb-1.5 text-foreground">{label}</p>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="size-2 rounded-sm" style={{ backgroundColor: 'var(--token-input)' }} />
            <span className="text-muted-foreground">{t("token.input")}:</span>
            <span className="font-medium text-foreground">{data.input_tokens?.toLocaleString() ?? 0}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="size-2 rounded-sm" style={{ backgroundColor: 'var(--token-cache)' }} />
            <span className="text-muted-foreground">{t("token.cacheRead") || "缓存"}:</span>
            <span className="font-medium text-foreground">{data.cache_read?.toLocaleString() ?? 0}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="size-2 rounded-sm" style={{ backgroundColor: 'var(--token-output)' }} />
            <span className="text-muted-foreground">{t("token.output")}:</span>
            <span className="font-medium text-foreground">{data.output_tokens?.toLocaleString() ?? 0}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="size-2 rounded-sm" style={{ backgroundColor: 'var(--token-reasoning)' }} />
            <span className="text-muted-foreground">{t("token.reasoning")}:</span>
            <span className="font-medium text-foreground">{data.reasoning?.toLocaleString() ?? 0}</span>
          </div>
          <div className="pt-1 mt-1 border-t border-border flex items-center gap-2">
            <span className="text-muted-foreground">{t("token.total")}:</span>
            <span className="font-semibold text-foreground">{data.total_tokens?.toLocaleString() ?? 0}</span>
          </div>
        </div>
      </div>
    )
  }
  return null
}

export function TokenStatsPanel({ currentConversation }: TokenStatsPanelProps) {
  const { t } = useI18n()
  const [isFlipped, setIsFlipped] = useState(false)
  const [dailyStats, setDailyStats] = useState<DailyStat[]>([])
  const [isLoadingStats, setIsLoadingStats] = useState(false)

  // Get cumulative tokens from conversation (or default to 0)
  const tokens = {
    input_tokens: currentConversation?.input_tokens ?? 0,
    cache_read: currentConversation?.cache_read ?? 0,
    output_tokens: currentConversation?.output_tokens ?? 0,
    reasoning: currentConversation?.reasoning ?? 0,
    total_tokens: currentConversation?.total_tokens ?? 0,
  }

  // Fetch daily stats when flipped
  const fetchDailyStats = useCallback(async () => {
    setIsLoadingStats(true)
    try {
      const response = await fetch(`/api/v1/chat/stats/daily?days=7`)
      if (response.ok) {
        const data = await response.json()
        setDailyStats(data)
      }
    } catch (error) {
      console.error("Failed to fetch daily stats:", error)
    } finally {
      setIsLoadingStats(false)
    }
  }, [])

  useEffect(() => {
    if (isFlipped && dailyStats.length === 0) {
      fetchDailyStats()
    }
  }, [isFlipped, dailyStats.length, fetchDailyStats])

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

  // Prepare chart data
  const chartData = dailyStats.map(d => ({
    date: formatDate(d.date),
    input_tokens: d.input_tokens,
    cache_read: d.cache_read,
    output_tokens: d.output_tokens,
    reasoning: d.reasoning,
    total_tokens: d.total_tokens,
  }))

  return (
    <div style={{ perspective: '1000px' }}>
      <div
        className="relative transition-transform duration-500 ease-out"
        style={{
          transformStyle: 'preserve-3d',
          transform: isFlipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
        }}
      >
        {/* Front Side */}
        <div 
          className={cn(
            "rounded-2xl bg-gradient-to-br from-muted/30 to-muted/50",
            "border border-border/50 overflow-hidden",
            "backdrop-blur-sm shadow-lg"
          )}
          style={{ backfaceVisibility: 'hidden' }}
        >
          {/* Header */}
          <div className="p-3 flex items-center justify-between border-b border-border/30 bg-muted/20">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setIsFlipped(true)}
                className="flex items-center justify-center cursor-pointer hover:opacity-80 transition-opacity"
                title={t("token.flipToStats")}
              >
              <div
                className="icon-money-dual"
              />
              </button>
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

        {/* Back Side */}
        <div 
          className={cn(
            "absolute inset-0",
            "rounded-2xl bg-gradient-to-br from-muted/30 to-muted/50",
            "border border-border/50 overflow-hidden",
            "backdrop-blur-sm shadow-lg"
          )}
          style={{ 
            backfaceVisibility: 'hidden',
            transform: 'rotateY(180deg)',
          }}
        >
          {/* Header */}
          <div className="p-3 flex items-center justify-between border-b border-border/30 bg-muted/20">
            <button
              type="button"
              onClick={() => setIsFlipped(false)}
              className="size-7 rounded-lg flex items-center justify-center cursor-pointer hover:bg-muted/50 transition-colors"
              title={t("token.flipBack")}
            >
              <div className="icon-arrow-left text-muted-foreground" />
            </button>
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-semibold text-foreground">
                {t("token.title")}
              </span>
            </div>
            <div className="size-7" />
          </div>

          {/* Chart */}
          <div className="p-3 h-[260px]">
            {isLoadingStats ? (
              <div className="h-full flex flex-col items-center justify-center gap-2">
                <Activity className="size-5 animate-pulse text-muted-foreground" />
                <span className="text-xs text-muted-foreground">{t("token.statsLoading")}</span>
              </div>
            ) : dailyStats.length === 0 ? (
              <div className="h-full flex items-center justify-center text-muted-foreground text-xs">
                {t("kanban.noData")}
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart 
                  data={chartData} 
                  margin={{ top: 10, right: 10, left: -15, bottom: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="var(--border)"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="date"
                    tick={{ fill: 'var(--text-dim)', fontSize: 10 }}
                    axisLine={{ stroke: 'var(--border)' }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: 'var(--text-dim)', fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={formatNumber}
                  />
                  <RechartsTooltip content={<ChartTooltip />} />
                  <Bar 
                    dataKey="input_tokens" 
                    stackId="a" 
                    fill="var(--token-input)" 
                    radius={[0, 0, 0, 0]}
                  />
                  <Bar 
                    dataKey="cache_read" 
                    stackId="a" 
                    fill="var(--token-cache)" 
                    radius={[0, 0, 0, 0]}
                  />
                  <Bar 
                    dataKey="output_tokens" 
                    stackId="a" 
                    fill="var(--token-output)" 
                    radius={[0, 0, 0, 0]}
                  />
                  <Bar 
                    dataKey="reasoning" 
                    stackId="a" 
                    fill="var(--token-reasoning)" 
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}