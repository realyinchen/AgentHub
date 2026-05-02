import { useState, useMemo } from "react"
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

import { DARK_THEME } from "../styles/theme"

type ChartType = "count" | "tokens" | "input" | "output" | "reasoning"

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
}

// Unified chart config
const chartTypeConfigs: Record<ChartType, {
  color: string
  icon: React.ElementType
  label: string
}> = {
  count: {
    color: DARK_THEME.nodeAI,
    icon: MessageSquare,
    label: "Conversations",
  },
  tokens: {
    color: DARK_THEME.textSecondary,
    icon: Coins,
    label: "Total Tokens",
  },
  input: {
    color: DARK_THEME.success,
    icon: ArrowDownToLine,
    label: "Input Tokens",
  },
  output: {
    color: DARK_THEME.warning,
    icon: ArrowUpFromLine,
    label: "Output Tokens",
  },
  reasoning: {
    color: DARK_THEME.textDim,
    icon: BrainCircuit,
    label: "Reasoning",
  },
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

function CustomTooltip({ active, payload, label }: any) {
  if (active && payload && payload.length) {
    return (
      <div
        className="rounded-lg px-4 py-3"
        style={{
          background: DARK_THEME.bgPanel,
          border: `1px solid ${DARK_THEME.border}`,
        }}
      >
        <p className="text-xs mb-1" style={{ color: DARK_THEME.textSecondary }}>{label}</p>
        <p className="text-lg font-bold" style={{ color: DARK_THEME.textPrimary }}>
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
}: {
  type: ChartType
  data: DailyStat[]
  isActive: boolean
  onClick: () => void
}) {
  const config = chartTypeConfigs[type]
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

  const activeBg = DARK_THEME.nodeAILight
  const activeBorder = DARK_THEME.nodeAIBorder

  return (
    <button
      onClick={onClick}
      className="w-full p-4 rounded-xl text-left transition-all cursor-pointer"
      style={{
        background: isActive ? activeBg : DARK_THEME.bgPanel,
        border: `1px solid ${isActive ? activeBorder : DARK_THEME.border}`,
        transform: isActive ? 'translateY(-1px)' : 'none',
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-2xl font-bold tabular-nums" style={{ color: DARK_THEME.textPrimary }}>
            {formatNumber(total)}
          </div>
          <div className="text-xs mt-1" style={{ color: DARK_THEME.textSecondary }}>
            {config.label}
          </div>
        </div>
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{
            background: isActive ? activeBg : 'rgba(255,255,255,0.04)',
            border: `1px solid ${isActive ? activeBorder : DARK_THEME.border}`,
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
              color: changePercent >= 0 ? DARK_THEME.success : DARK_THEME.error,
            }}
          >
            {changePercent >= 0 ? "+" : ""}{changePercent.toFixed(1)}%
          </span>
          <span className="text-xs" style={{ color: DARK_THEME.textDim }}>
            vs last 7 days
          </span>
        </div>
      )}

      <div className="mt-3">
        <Sparkline data={data} color={config.color} type={type} />
      </div>
    </button>
  )
}

export function DailyStatsChart({ data, isLoading }: DailyStatsChartProps) {
  const [activeType, setActiveType] = useState<ChartType>("count")
  const config = chartTypeConfigs[activeType]

  if (isLoading) {
    return (
      <div
        className="w-full h-[400px] flex items-center justify-center rounded-xl"
        style={{ background: DARK_THEME.bgPanel, border: `1px solid ${DARK_THEME.border}` }}
      >
        <div className="flex flex-col items-center gap-3">
          <Activity className="w-8 h-8 animate-pulse" style={{ color: DARK_THEME.nodeAI }} />
          <span style={{ color: DARK_THEME.textSecondary }}>Loading stats...</span>
        </div>
      </div>
    )
  }

  if (!data || data.length === 0) {
    return (
      <div
        className="w-full h-[300px] flex items-center justify-center rounded-xl"
        style={{ background: DARK_THEME.bgPanel, border: `1px solid ${DARK_THEME.border}` }}
      >
        <span style={{ color: DARK_THEME.textDim }}>No data available</span>
      </div>
    )
  }

  const chartData = data.map(d => ({
    date: formatDate(d.date),
    value: getField(d, activeType),
  }))

  return (
    <div
      className="w-full rounded-xl overflow-hidden"
      style={{ background: DARK_THEME.bgPanel, border: `1px solid ${DARK_THEME.border}` }}
    >
      {/* Metrics Row */}
      <div
        className="grid grid-cols-5 gap-3 p-4"
        style={{ borderBottom: `1px solid ${DARK_THEME.border}` }}
      >
        {(Object.keys(chartTypeConfigs) as ChartType[]).map(type => (
          <MetricCard
            key={type}
            type={type}
            data={data}
            isActive={activeType === type}
            onClick={() => setActiveType(type)}
          />
        ))}
      </div>

      {/* Chart Area */}
      <div className="p-4 h-[300px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke={DARK_THEME.chartGrid}
              vertical={false}
            />
            <XAxis
              dataKey="date"
              tick={{ fill: DARK_THEME.textDim, fontSize: 11 }}
              axisLine={{ stroke: DARK_THEME.border }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: DARK_THEME.textDim, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={formatNumber}
            />
            <Tooltip content={<CustomTooltip />} />
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