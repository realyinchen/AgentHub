import { HelpCircle } from "lucide-react"
import type { ConversationInDB } from "@/types"
import { useI18n } from "@/i18n"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface TokenStatsPanelProps {
  /** Current conversation with cumulative token stats */
  currentConversation: ConversationInDB | null
}

// Maximum token limit for the bar chart (128k)
const MAX_TOKENS = 128000

interface TokenBarProps {
  label: string
  value: number
  color: string
  tooltip?: string
}

function TokenBar({ label, value, color, tooltip }: TokenBarProps) {
  // Calculate fill ratio based on 128k max
  const ratio = Math.min((value / MAX_TOKENS) * 100, 100)

  return (
    <div className="space-y-1">
      <div className="flex justify-between items-center text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <span>{label}</span>
          {tooltip && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <HelpCircle className="size-3 cursor-help" />
                </TooltipTrigger>
                <TooltipContent side="top" className="text-xs">
                  {tooltip}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </div>
        <span>{value.toLocaleString()}</span>
      </div>
      <div className="h-2 bg-muted rounded-full overflow-hidden">
        <div
          className="h-full transition-all duration-300 rounded-full"
          style={{
            width: `${ratio}%`,
            backgroundColor: color,
          }}
        />
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

  return (
    <div className="space-y-3 p-2 rounded-lg bg-muted/50 border">
      <div className="text-xs font-medium text-muted-foreground">
        {t("token.title")}
      </div>
      
      {/* Input Tokens */}
      <TokenBar
        label={t("token.input")}
        value={tokens.input_tokens}
        color="#3b82f6"
        tooltip={t("token.inputTooltip")}
      />
      
      {/* Cache Read */}
      <TokenBar
        label={t("token.cacheRead")}
        value={tokens.cache_read}
        color="#8b5cf6"
      />
      
      {/* Output Tokens */}
      <TokenBar
        label={t("token.output")}
        value={tokens.output_tokens}
        color="#10b981"
      />
      
      {/* Reasoning Tokens */}
      <TokenBar
        label={t("token.reasoning")}
        value={tokens.reasoning}
        color="#f59e0b"
      />
      
      {/* Total */}
      <div className="pt-2 border-t">
        <TokenBar
          label={t("token.total")}
          value={tokens.total_tokens}
          color="#6366f1"
        />
      </div>
    </div>
  )
}