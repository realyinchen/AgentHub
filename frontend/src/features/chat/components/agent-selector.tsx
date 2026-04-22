import { useMemo } from "react"
import { useI18n } from "@/i18n"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import type { AgentInDB } from "@/types"

interface AgentSelectorProps {
  agents: AgentInDB[]
  selectedAgentId: string
  onSelectAgent: (agentId: string) => void
  disabled?: boolean
}

/**
 * Get agent category based on capabilities
 */
function getAgentCategory(agentId: string, description: string): { label: string; color: string } {
  const id = agentId.toLowerCase()
  const desc = description.toLowerCase()

  if (id.includes("nav") || desc.includes("map") || desc.includes("导航") || desc.includes("地图")) {
    return { label: "Navigation", color: "bg-blue-500/10 text-blue-600 dark:text-blue-400" }
  }

  if (id.includes("search") || desc.includes("search") || desc.includes("搜索") || desc.includes("查询")) {
    return { label: "Search", color: "bg-green-500/10 text-green-600 dark:text-green-400" }
  }

  if (id.includes("tool") || desc.includes("tool") || desc.includes("工具")) {
    return { label: "Utility", color: "bg-purple-500/10 text-purple-600 dark:text-purple-400" }
  }

  return { label: "Chat", color: "bg-amber-500/10 text-amber-600 dark:text-amber-400" }
}

/**
 * Truncate description to max length
 */
function truncateDescription(desc: string, maxLength: number = 50): string {
  if (desc.length <= maxLength) return desc
  return desc.slice(0, maxLength) + "..."
}

/**
 * Agent selector component with descriptions
 */
export function AgentSelector({
  agents,
  selectedAgentId,
  onSelectAgent,
  disabled = false,
}: AgentSelectorProps) {
  const { t } = useI18n()

  // Sort agents to always show current selected agent first
  const sortedAgents = useMemo(() => {
    return [...agents].sort((a, b) => {
      if (a.agent_id === selectedAgentId) return -1
      if (b.agent_id === selectedAgentId) return 1
      return a.agent_id.localeCompare(b.agent_id)
    })
  }, [agents, selectedAgentId])

  // Get selected agent info
  const selectedAgent = agents.find(a => a.agent_id === selectedAgentId)

  return (
    <Select
      value={selectedAgentId}
      onValueChange={(value) => {
        if (!disabled) {
          onSelectAgent(value)
        }
      }}
      disabled={disabled}
    >
      <SelectTrigger
        size="sm"
        className="h-9 px-3 text-sm w-[140px] border-border/60 bg-background/80 backdrop-blur-sm hover:bg-accent/30 hover:border-primary/40 transition-all duration-200"
      >
        <SelectValue placeholder={t("agent.select")}>
          {selectedAgent && (
            <span className="truncate">{selectedAgent.agent_id}</span>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent
        position="popper"
        side="top"
        align="start"
        className="w-[280px] border-border/60 bg-popover/95 backdrop-blur-md"
      >
        {sortedAgents.map((agent) => {
          const category = getAgentCategory(agent.agent_id, agent.description)

          return (
            <SelectItem
              key={agent.agent_id}
              value={agent.agent_id}
              className="py-2.5 px-3 cursor-pointer focus:bg-accent/50"
            >
              <div className="flex flex-col gap-1 w-full min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm truncate">
                    {agent.agent_id}
                  </span>
                  <Badge
                    variant="secondary"
                    className={`text-[9px] px-1.5 py-0 h-4 shrink-0 ${category.color}`}
                  >
                    {category.label}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground truncate">
                  {truncateDescription(agent.description)}
                </p>
              </div>
            </SelectItem>
          )
        })}
      </SelectContent>
    </Select>
  )
}
