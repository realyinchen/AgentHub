import { useState, useMemo } from "react"
import { useI18n } from "@/i18n"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts"
import {
  MessageSquare,
  Coins,
  ArrowDownToLine,
  ArrowUpFromLine,
  BrainCircuit,
  Activity,
} from "lucide-react"

import { DARK_THEME, LIGHT_THEME } from "../styles/theme"

type ChartType = "count" | "tokens" | "input" | "output" | "reasoning"

type ThemeValue = "light" | "dark"

type DailyStat = {
  date: string
  count: number
  total_tokens: number
  input_tokens: number
  output_tokens: number
  reasoning: number
  cache_read?: number
}

type DailyStatsChartProps = {
  data: DailyStat[]
  isLoading?: boolean
  theme?: ThemeValue
}

// Get theme object by name, default to dark
function getTheme(theme?: ThemeValue) {
  return theme === "light" ? LIGHT_THEME : DARK_THEME
}

const formatNumber = (num: number): string => {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + "M"
  if (num >= 1000) return (num / 1000).toFixed(1) + "K"
  return num.toString()
}

const formatDate = (dateStr: string): string => {
  const date = new Date(dateStr)
  return `${date.getMonth() + 1}/${date.getDate()}`
}

const getField = (d: DailyStat, type: ChartType): number => {
  switch (type) {
    case "count": return d.count
    case "tokens": return d.total_tokens
    case "input": return d.input_tokens
    case "output": return d.output_tokens
    case "reasoning": return d.reasoning
  }
}

// Get chart type configs for a given theme
function getChartTypeConfigs(
  theme: ReturnType<typeof getTheme>,
  t: (key: string) => string
): Record<ChartType, {
  color: string
  icon: React.ElementType
  label: string
}> {
  return {
    count: {
      color: theme.nodeAI,
      icon: MessageSquare,
      label: t("kanban.chart.count"),
    },
    tokens: {
      color: theme.textSecondary,
      icon: Coins,
      label: t("kanban.chart.tokens"),
    },
    input: {
      color: theme.success,
      icon: ArrowDownToLine,
      label: t("kanban.chart.input"),
    },
    output: {
      color: theme.warning,
      icon: ArrowUpFromLine,
      label: t("kanban.chart.output"),
    },
    reasoning: {
      color: theme.textDim,
      icon: BrainCircuit,
      label: t("kanban.chart.reasoning"),
    },
  }
}

function Sparkline({ data, color, type }: { data: DailyStat[]; color: string; type: ChartType }) {
  const sparkData = data.slice(-14).map(d => ({
    value: getField(d, type)
  }))
  const max = Math.max(...sparkData.map(d => d.value), 1)

  return (
    <div className="h-6 w-full flex items-end gap-px">
      {sparkData.map((d, i) => {
        const height = max > 0 ? (d.value / max) * 100 : 0
        return (
          <div
            key={i}
            className="flex-1 rounded-sm transition-all duration-200"
            style={{
              height: `${Math.max(height, 5)}%`,
              backgroundColor: color,
              opacity: 0.5,
            }}
          />
        )
      })}
    </div>
  )
}

function CustomTooltip({ active, payload, label, theme }: { active?: boolean; payload?: any; label?: string; theme: ReturnType<typeof getTheme> }) {
  if (active && payload && payload.length) {
    return (
      <div
        className="rounded-lg px-4 py-3"
        style={{
          background: theme.bgPanel,
          border: `1px solid ${theme.border}`,
        }}
      >
        <p className="text-xs mb-1" style={{ color: theme.textSecondary }}>{label}</p>
        <p className="text-lg font-bold" style={{ color: theme.textPrimary }}>
          {formatNumber(payload[0].value)}
        </p>
      </div>
    )
  }
  return null
}

function MetricCard({
  type,
  data,
  isActive,
  onClick,
  theme,
  t,
}: {
  type: ChartType
  data: DailyStat[]
  isActive: boolean
  onClick: () => void
  theme: ReturnType<typeof getTheme>
  t: (key: string) => string
}) {
  const configs = getChartTypeConfigs(theme, t)
  const config = configs[type]
  const Icon = config.icon

  const total = useMemo(() =>
    data.reduce((sum, d) => sum + getField(d, type), 0)
    , [data, type])

  const changePercent = useMemo(() => {
    if (data.length < 14) return null
    const last7 = data.slice(-7).reduce((sum, d) => sum + getField(d, type), 0)
    const prev7 = data.slice(-14, -7).reduce((sum, d) => sum + getField(d, type), 0)
    if (prev7 === 0) return last7 > 0 ? 100 : 0
    return ((last7 - prev7) / prev7) * 100
  }, [data, type])

  const activeBg = theme.nodeAILight
  const activeBorder = theme.nodeAIBorder

  return (
    <button
      onClick={onClick}
      className="w-full p-4 rounded-xl text-left transition-all cursor-pointer"
      style={{
        background: isActive ? activeBg : theme.bgPanel,
        border: `1px solid ${isActive ? activeBorder : theme.border}`,
        transform: isActive ? 'translateY(-1px)' : 'none',
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-2xl font-bold tabular-nums" style={{ color: theme.textPrimary }}>
            {formatNumber(total)}
          </div>
          <div className="text-xs mt-1" style={{ color: theme.textSecondary }}>
            {config.label}
          </div>
        </div>
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{
            background: isActive ? activeBg : (theme === DARK_THEME ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'),
            border: `1px solid ${isActive ? activeBorder : theme.border}`,
          }}
        >
          <Icon className="w-4 h-4" style={{ color: config.color }} />
        </div>
      </div>

      {changePercent !== null && (
        <div className="mt-3 flex items-center gap-1.5">
          <span
            className="text-xs font-medium"
            style={{
              color: changePercent >= 0 ? theme.success : theme.error,
            }}
          >
            {changePercent >= 0 ? "+" : ""}{changePercent.toFixed(1)}%
          </span>
          <span className="text-xs" style={{ color: theme.textDim }}>
            {t("kanban.vsLast7Days")}
          </span>
        </div>
      )}

      <div className="mt-3">
        <Sparkline data={data} color={config.color} type={type} />
      </div>
    </button>
  )
}

export function DailyStatsChart({ data, isLoading, theme: themeProp }: DailyStatsChartProps) {
  const { t } = useI18n()
  const [activeType, setActiveType] = useState<ChartType>("count")
  const theme = getTheme(themeProp)
  const chartTypeConfigs = getChartTypeConfigs(theme, t)
  const config = chartTypeConfigs[activeType]

  if (isLoading) {
    return (
      <div
        className="w-full min-h-[300px] flex-1 flex items-center justify-center rounded-xl"
        style={{ background: theme.bgPanel, border: `1px solid ${theme.border}` }}
      >
        <div className="flex flex-col items-center gap-3">
          <Activity className="w-8 h-8 animate-pulse" style={{ color: theme.nodeAI }} />
          <span style={{ color: theme.textSecondary }}>{t("kanban.loading")}</span>
        </div>
      </div>
    )
  }

  if (!data || data.length === 0) {
    return (
      <div
        className="w-full min-h-[250px] flex-1 flex items-center justify-center rounded-xl"
        style={{ background: theme.bgPanel, border: `1px solid ${theme.border}` }}
      >
        <span style={{ color: theme.textDim }}>{t("kanban.noData")}</span>
      </div>
    )
  }

  const chartData = data.map(d => ({
    date: formatDate(d.date),
    value: getField(d, activeType),
  }))

  return (
    <div
      className="w-full rounded-xl overflow-hidden flex flex-col"
      style={{ background: theme.bgPanel, border: `1px solid ${theme.border}` }}
    >
      {/* Metrics Row - always 5 columns in one row */}
      <div
        className="grid grid-cols-5 gap-3 p-4 flex-shrink-0"
        style={{ borderBottom: `1px solid ${theme.border}` }}
      >
        {(Object.keys(chartTypeConfigs) as ChartType[]).map(type => (
          <MetricCard
            key={type}
            type={type}
            data={data}
            isActive={activeType === type}
            onClick={() => setActiveType(type)}
            theme={theme}
            t={t}
          />
        ))}
      </div>

      {/* Chart Area - fixed height to prevent collapse */}
      <div className="p-4 h-[300px] flex-shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke={theme.chartGrid}
              vertical={false}
            />
            <XAxis
              dataKey="date"
              tick={{ fill: theme.textDim, fontSize: 11 }}
              axisLine={{ stroke: theme.border }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: theme.textDim, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={formatNumber}
            />
            <Tooltip content={<CustomTooltip theme={theme} />} />
            <Bar
              dataKey="value"
              radius={[4, 4, 0, 0]}
              maxBarSize={40}
            >
              {chartData.map((_entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={config.color}
                  opacity={0.8}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}