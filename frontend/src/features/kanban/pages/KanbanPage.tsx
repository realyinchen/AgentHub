import { useState, useEffect, useCallback } from "react"
import { useSearchParams, useNavigate } from "react-router-dom"
import { LineChart, BarChart3, MessageSquare } from "lucide-react"

import { DailyStatsChart } from "../components/daily-stats-chart"
import { TimeRangeSelector } from "../components/TimeRangeSelector"
import { ConversationGrid } from "../components/ConversationGrid"
import { DARK_THEME } from "../styles/theme"

type DailyStat = {
  date: string
  count: number
  total_tokens: number
  input_tokens: number
  output_tokens: number
  reasoning: number
  cache_read: number
}

type TabType = "stats" | "conversations"

export function KanbanPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const tabFromUrl = searchParams.get("tab")
  const [activeTab, setActiveTab] = useState<TabType>(
    tabFromUrl === "conversations" ? "conversations" : "stats"
  )

  const handleTabChange = (tab: TabType) => {
    setActiveTab(tab)
    if (tab === "conversations") {
      navigate("/kanban?tab=conversations", { replace: true })
    } else {
      navigate("/kanban", { replace: true })
    }
  }
  const [timeRange, setTimeRange] = useState<number | { start: Date; end: Date }>(30)
  const [dailyStats, setDailyStats] = useState<DailyStat[]>([])
  const [isLoadingStats, setIsLoadingStats] = useState(true)
  const [conversationRefreshKey, setConversationRefreshKey] = useState(0)

  // Fetch daily stats
  const fetchDailyStats = useCallback(async () => {
    setIsLoadingStats(true)
    try {
      let days: number
      if (typeof timeRange === "number") {
        days = timeRange
      } else {
        // Calculate days from custom range
        const diffTime = Math.abs(timeRange.end.getTime() - timeRange.start.getTime())
        days = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1
      }

      const response = await fetch(`/api/v1/chat/stats/daily?days=${days}`)
      if (response.ok) {
        const data = await response.json()
        setDailyStats(data)
      }
    } catch (error) {
      console.error("Failed to fetch daily stats:", error)
    } finally {
      setIsLoadingStats(false)
    }
  }, [timeRange])

  useEffect(() => {
    fetchDailyStats()
  }, [fetchDailyStats])

  const handleTimeRangeChange = (newRange: number | { start: Date; end: Date }) => {
    setTimeRange(newRange)
    if (activeTab === "conversations") {
      setConversationRefreshKey(prev => prev + 1)
    }
  }

  const tabs = [
    { id: "stats" as TabType, label: "Statistics", icon: BarChart3 },
    { id: "conversations" as TabType, label: "Conversations", icon: MessageSquare },
  ]

  return (
    <div
      className="min-h-screen w-full"
      style={{ background: DARK_THEME.bgMain }}
    >
      {/* Header */}
      <div
        className="border-b"
        style={{ borderColor: DARK_THEME.border }}
      >
        <div className="max-w-6xl mx-auto px-8 py-4">
          <div className="flex items-center justify-between">
            {/* Title */}
            <div className="flex items-center gap-3">
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center"
                style={{
                  background: DARK_THEME.nodeAILight,
                  border: `1px solid ${DARK_THEME.borderActive}`,
                }}
              >
                <LineChart className="w-5 h-5" style={{ color: DARK_THEME.nodeAI }} />
              </div>
              <div>
                <h1
                  className="text-xl font-bold"
                  style={{ color: DARK_THEME.textPrimary }}
                >
                  AgentHub Kanban
                </h1>
                <p
                  className="text-sm"
                  style={{ color: DARK_THEME.textDim }}
                >
                  Explore agent execution traces and statistics
                </p>
              </div>
            </div>

            {/* Time Range Selector */}
            <div className="relative">
              <TimeRangeSelector
                value={timeRange}
                onChange={handleTimeRangeChange}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div
        className="border-b"
        style={{ borderColor: DARK_THEME.border }}
      >
        <div className="max-w-6xl mx-auto px-8">
          <div className="flex items-center gap-1">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => handleTabChange(tab.id)}
                className="flex items-center gap-2 px-4 py-3 text-sm font-medium transition-all cursor-pointer"
                style={{
                  background: activeTab === tab.id
                    ? 'rgba(91,140,255,0.08)'
                    : 'transparent',
                  borderBottom: activeTab === tab.id
                    ? `2px solid ${DARK_THEME.nodeAI}`
                    : '2px solid transparent',
                  color: activeTab === tab.id
                    ? DARK_THEME.nodeAI
                    : DARK_THEME.textSecondary,
                  marginBottom: '-1px',
                }}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-8 py-6">
        {activeTab === "stats" && (
          <DailyStatsChart data={dailyStats} isLoading={isLoadingStats} />
        )}

        {activeTab === "conversations" && (
          <ConversationGrid refreshKey={conversationRefreshKey} />
        )}
      </main>
    </div>
  )
}