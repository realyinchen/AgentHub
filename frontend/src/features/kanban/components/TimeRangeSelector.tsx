import { useState } from "react"
import { Calendar, ChevronDown, Check } from "lucide-react"

import { DARK_THEME } from "../styles/theme"

type TimeRangeSelectorProps = {
  value: number | { start: Date; end: Date }
  onChange: (value: number | { start: Date; end: Date }) => void
}

const presetOptions = [
  { label: "7 days", value: 7 },
  { label: "30 days", value: 30 },
  { label: "90 days", value: 90 },
]

function formatDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function formatDisplayDate(date: Date): string {
  return `${date.getMonth() + 1}/${date.getDate()}`
}

export function TimeRangeSelector({ value, onChange }: TimeRangeSelectorProps) {
  const [isCustomOpen, setIsCustomOpen] = useState(false)
  const [customStart, setCustomStart] = useState<string>("")
  const [customEnd, setCustomEnd] = useState<string>("")

  const isPreset = typeof value === "number"
  const selectedPreset = isPreset ? value : null
  const isCustom = !isPreset

  const displayText = isPreset
    ? `${value} days`
    : `${formatDisplayDate(value.start)} - ${formatDisplayDate(value.end)}`

  const handlePresetClick = (days: number) => {
    onChange(days)
    setIsCustomOpen(false)
  }

  const handleCustomApply = () => {
    if (customStart && customEnd) {
      const start = new Date(customStart)
      const end = new Date(customEnd)
      // Ensure start is before end
      if (start <= end) {
        onChange({ start, end })
      } else {
        onChange({ start: end, end: start })
      }
      setIsCustomOpen(false)
    }
  }

  const handleCustomClick = () => {
    // Initialize with default dates if not set
    if (!customStart || !customEnd) {
      const today = new Date()
      const thirtyDaysAgo = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000)
      setCustomStart(formatDate(thirtyDaysAgo))
      setCustomEnd(formatDate(today))
    }
    setIsCustomOpen(!isCustomOpen)
  }

  return (
    <div className="flex items-center gap-2">
      {/* Preset buttons */}
      {presetOptions.map((option) => (
        <button
          key={option.value}
          onClick={() => handlePresetClick(option.value)}
          className="px-3 py-1.5 rounded-lg text-sm font-medium transition-all cursor-pointer"
          style={{
            background: selectedPreset === option.value
              ? DARK_THEME.nodeAILight
              : 'rgba(255,255,255,0.04)',
            border: `1px solid ${selectedPreset === option.value
              ? DARK_THEME.borderActive
              : DARK_THEME.border}`,
            color: selectedPreset === option.value
              ? DARK_THEME.nodeAI
              : DARK_THEME.textSecondary,
          }}
        >
          {option.label}
        </button>
      ))}

      {/* Custom date range */}
      <button
        onClick={handleCustomClick}
        className="px-3 py-1.5 rounded-lg text-sm font-medium transition-all cursor-pointer flex items-center gap-1.5"
        style={{
          background: isCustom
            ? DARK_THEME.nodeAILight
            : 'rgba(255,255,255,0.04)',
          border: `1px solid ${isCustom
            ? DARK_THEME.borderActive
            : DARK_THEME.border}`,
          color: isCustom
            ? DARK_THEME.nodeAI
            : DARK_THEME.textSecondary,
        }}
      >
        <Calendar className="w-3.5 h-3.5" />
        <span>Custom</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${isCustomOpen ? 'rotate-180' : ''}`} />
      </button>

      {/* Custom date picker dropdown */}
      {isCustomOpen && (
        <div
          className="absolute top-full mt-2 right-0 p-4 rounded-xl z-50"
          style={{
            background: DARK_THEME.bgPanel,
            border: `1px solid ${DARK_THEME.border}`,
          }}
        >
          <div className="flex gap-4 items-end">
            <div className="space-y-2">
              <label
                className="text-xs font-medium block"
                style={{ color: DARK_THEME.textSecondary }}
              >
                Start Date
              </label>
              <input
                type="date"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                className="h-9 px-3 rounded-lg text-sm"
                style={{
                  background: DARK_THEME.bgMain,
                  border: `1px solid ${DARK_THEME.border}`,
                  color: DARK_THEME.textPrimary,
                }}
              />
            </div>
            <div className="space-y-2">
              <label
                className="text-xs font-medium block"
                style={{ color: DARK_THEME.textSecondary }}
              >
                End Date
              </label>
              <input
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="h-9 px-3 rounded-lg text-sm"
                style={{
                  background: DARK_THEME.bgMain,
                  border: `1px solid ${DARK_THEME.border}`,
                  color: DARK_THEME.textPrimary,
                }}
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setIsCustomOpen(false)}
                className="px-3 py-1.5 rounded-lg text-sm cursor-pointer"
                style={{
                  background: 'transparent',
                  border: `1px solid ${DARK_THEME.border}`,
                  color: DARK_THEME.textSecondary,
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleCustomApply}
                disabled={!customStart || !customEnd}
                className="px-3 py-1.5 rounded-lg text-sm cursor-pointer flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                style={{
                  background: DARK_THEME.nodeAI,
                  color: '#fff',
                }}
              >
                <Check className="w-3.5 h-3.5" />
                Apply
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Display current range */}
      <span
        className="text-xs ml-2"
        style={{ color: DARK_THEME.textDim }}
      >
        {displayText}
      </span>
    </div>
  )
}