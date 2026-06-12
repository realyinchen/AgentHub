import { useState, useEffect, useCallback, useMemo } from "react"
import { Activity } from "lucide-react"
import type { ConversationInDB } from "@/types"
import { useI18n } from "@/i18n"
import { cn } from "@/lib/utils"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  CartesianGrid,
} from "recharts"

interface TokenStatsPanelProps {
  /** Current conversation with cumulative token stats */
  currentConversation: ConversationInDB | null
}

type DailyStat = {
  date: string
  conversation_count: number
  total_tokens: number
  input_tokens: number
  output_tokens: number
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
            <div className="size-2 rounded-sm" style={{ backgroundColor: 'var(--token-output)' }} />
            <span className="text-muted-foreground">{t("token.output")}:</span>
            <span className="font-medium text-foreground">{data.output_tokens?.toLocaleString() ?? 0}</span>
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

// Donut Chart Component
interface DonutChartProps {
  inputTokens: number
  outputTokens: number
  totalTokens: number
}

function DonutChart({ inputTokens, outputTokens, totalTokens }: DonutChartProps) {
  const { t } = useI18n()

  // Calculate percentages
  const inputPercentage = totalTokens > 0 ? (inputTokens / totalTokens) * 100 : 0
  const outputPercentage = totalTokens > 0 ? (outputTokens / totalTokens) * 100 : 0

  // SVG parameters
  const size = 140
  const strokeWidth = 16
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const center = size / 2

  // Calculate stroke dash arrays
  // Input arc (starts from top, goes clockwise)
  const inputDash = (inputPercentage / 100) * circumference
  // Output arc (continues after input)
  const outputDash = (outputPercentage / 100) * circumference

  // Rotation to start from top (-90 degrees)
  const rotation = -90

  return (
    <div className="relative flex items-center justify-center">
      {/* Circular background container */}
      <div
        className="rounded-full overflow-hidden"
        style={{ width: size, height: size }}
      >
        <svg
          width={size}
          height={size}
          className="transform transition-transform duration-300"
          style={{ transform: `rotate(${rotation}deg)` }}
        >
          {/* Background track */}
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke="var(--token-track)"
            strokeWidth={strokeWidth}
          />

          {/* Input tokens arc (blue) */}
          {inputTokens > 0 && (
            <circle
              cx={center}
              cy={center}
              r={radius}
              fill="none"
              stroke="var(--token-input)"
              strokeWidth={strokeWidth}
              strokeDasharray={`${inputDash} ${circumference - inputDash}`}
              strokeLinecap="round"
              className="transition-all duration-500 ease-out"
            />
          )}

          {/* Output tokens arc (purple) */}
          {outputTokens > 0 && (
            <circle
              cx={center}
              cy={center}
              r={radius}
              fill="none"
              stroke="var(--token-output)"
              strokeWidth={strokeWidth}
              strokeDasharray={`${outputDash} ${circumference - outputDash}`}
              strokeDashoffset={-inputDash}
              strokeLinecap="round"
              className="transition-all duration-500 ease-out"
            />
          )}
        </svg>
      </div>

      {/* Center content */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-xs text-muted-foreground">{t("token.total")}</span>
        <span className="text-lg font-bold text-foreground">
          {totalTokens.toLocaleString()}
        </span>
      </div>
    </div>
  )
}

// Separate Chart Component - uses fixed dimensions to avoid ResponsiveContainer measurement issues
// Chart container is 200px height with p-3 (12px each side), so chart area is ~176px
// Width is flexible but we use a reasonable fixed width for the chart
interface DailyStatsChartProps {
  chartData: Array<{
    date: string
    input_tokens: number
    output_tokens: number
    total_tokens: number
  }>
}

function DailyStatsChart({ chartData }: DailyStatsChartProps) {
  // Fixed dimensions - no need for ResponsiveContainer measurement
  const chartWidth = 280
  const chartHeight = 176

  return (
    <div className="h-full w-full flex items-center justify-center">
      <BarChart
        width={chartWidth}
        height={chartHeight}
        data={chartData}
        margin={{ top: 10, right: 10, left: -15, bottom: 25 }}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="var(--border)"
          vertical={false}
        />
        <XAxis
          dataKey="date"
          interval={0}
          tick={{ fill: 'var(--text-dim)', fontSize: 10, angle: -45, textAnchor: 'end' }}
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
        {/* Stack order: input (bottom) → output (top) */}
        <Bar
          dataKey="input_tokens"
          stackId="a"
          fill="var(--token-input)"
          radius={[0, 0, 0, 0]}
        />
        <Bar
          dataKey="output_tokens"
          stackId="a"
          fill="var(--token-output)"
          radius={[4, 4, 0, 0]}
        />
      </BarChart>
    </div>
  )
}

export function TokenStatsPanel({ currentConversation }: TokenStatsPanelProps) {
  const { t } = useI18n()
  const [isFlipped, setIsFlipped] = useState(false)
  const [chartRenderKey, setChartRenderKey] = useState(0)
  const [dailyStats, setDailyStats] = useState<DailyStat[]>([])
  const [isLoadingStats, setIsLoadingStats] = useState(false)

  // Get cumulative tokens from conversation (or default to 0)
  const tokens = {
    input_tokens: currentConversation?.input_tokens ?? 0,
    output_tokens: currentConversation?.output_tokens ?? 0,
    total_tokens: currentConversation?.total_tokens ?? 0,
  }

  // Generate past N days date strings (YYYY-MM-DD format)
  const generatePastDays = (days: number): string[] => {
    const dates: string[] = []
    const today = new Date()
    for (let i = days - 1; i >= 0; i--) {
      const date = new Date(today)
      date.setDate(date.getDate() - i)
      dates.push(date.toISOString().split('T')[0])
    }
    return dates
  }

  // Fetch daily stats when flipped
  const fetchDailyStats = useCallback(async () => {
    setIsLoadingStats(true)
    try {
      const response = await fetch(`/api/v1/chat/stats/daily?days=7`)
      if (response.ok) {
        const data = await response.json()

        // Create a map from the API response
        const dataMap = new Map<string, DailyStat>()
        data.forEach((d: any) => {
          dataMap.set(d.date, {
            date: d.date,
            conversation_count: d.conversation_count ?? 0,
            total_tokens: d.total_tokens ?? 0,
            input_tokens: d.input_tokens ?? 0,
            output_tokens: d.output_tokens ?? 0,
          })
        })

        // Fill in missing dates with zero values
        const past7Days = generatePastDays(7)
        const filledData: DailyStat[] = past7Days.map(date => {
          return dataMap.get(date) || {
            date,
            conversation_count: 0,
            total_tokens: 0,
            input_tokens: 0,
            output_tokens: 0,
          }
        })

        setDailyStats(filledData)
      }
    } catch (error) {
      console.error("Failed to fetch daily stats:", error)
    } finally {
      setIsLoadingStats(false)
    }
  }, [])

  // Fetch data when flipped
  useEffect(() => {
    if (isFlipped) {
      fetchDailyStats()
    }
  }, [isFlipped, fetchDailyStats])

  // Handle transition end to trigger chart render after animation completes
  const handleTransitionEnd = useCallback(() => {
    if (isFlipped && chartRenderKey === 0) {
      // Increment key to force chart component to mount
      setChartRenderKey(prev => prev + 1)
    }
  }, [isFlipped, chartRenderKey])

  // Reset chart when flipping back
  useEffect(() => {
    if (!isFlipped) {
      setChartRenderKey(0)
    }
  }, [isFlipped])

  // Calculate percentages for display
  const inputPercentage = tokens.total_tokens > 0
    ? ((tokens.input_tokens / tokens.total_tokens) * 100).toFixed(1)
    : "0"
  const outputPercentage = tokens.total_tokens > 0
    ? ((tokens.output_tokens / tokens.total_tokens) * 100).toFixed(1)
    : "0"

  // Prepare chart data - memoized to prevent unnecessary re-renders
  const chartData = useMemo(() =>
    dailyStats.map(d => ({
      date: formatDate(d.date),
      input_tokens: d.input_tokens,
      output_tokens: d.output_tokens,
      total_tokens: d.total_tokens,
    })),
    [dailyStats]
  )

  // Determine if chart should render (only when key > 0 and data exists)
  const shouldRenderChart = chartRenderKey > 0 && chartData.length > 0

  return (
    <div style={{ perspective: '1000px' }}>
      <div
        className="relative transition-transform duration-500 ease-out"
        style={{
          transformStyle: 'preserve-3d',
          transform: isFlipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
        }}
        onTransitionEnd={handleTransitionEnd}
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
                <div className="icon-money-dual" />
              </button>
              <span className="text-sm font-semibold text-foreground">
                {t("token.title")}
              </span>
            </div>
          </div>

          {/* Donut Chart */}
          <div className="p-4 flex flex-col items-center">
            <DonutChart
              inputTokens={tokens.input_tokens}
              outputTokens={tokens.output_tokens}
              totalTokens={tokens.total_tokens}
            />

            {/* Legend - only show percentages */}
            <div className="mt-4 flex items-center gap-6 text-xs">
              <div className="flex items-center gap-1.5">
                <div
                  className="size-2.5 rounded-sm"
                  style={{ backgroundColor: 'var(--token-input)' }}
                />
                <span className="text-muted-foreground">{t("token.input")}</span>
                <span className="font-medium text-foreground">{inputPercentage}%</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div
                  className="size-2.5 rounded-sm"
                  style={{ backgroundColor: 'var(--token-output)' }}
                />
                <span className="text-muted-foreground">{t("token.output")}</span>
                <span className="font-medium text-foreground">{outputPercentage}%</span>
              </div>
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

          {/* Chart Container */}
          <div className="p-3 h-[200px] relative">
            {isLoadingStats ? (
              /* Loading state - fetching data */
              <div className="h-full flex flex-col items-center justify-center gap-2">
                <Activity className="size-5 animate-pulse text-muted-foreground" />
                <span className="text-xs text-muted-foreground">{t("token.statsLoading")}</span>
              </div>
            ) : !shouldRenderChart ? (
              /* Waiting for flip animation to complete */
              <div className="h-full flex flex-col items-center justify-center gap-2">
                <Activity className="size-5 animate-pulse text-muted-foreground" />
                <span className="text-xs text-muted-foreground">{t("token.statsLoading")}</span>
              </div>
            ) : (
              /* Chart - only mounts when renderKey changes after animation */
              <DailyStatsChart key={chartRenderKey} chartData={chartData} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}