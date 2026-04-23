import { useState, useEffect } from "react"
import { Shuffle } from "lucide-react"
import type { AgentInDB } from "@/types"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/i18n"

interface AgentCardProps {
  agent: AgentInDB
  index: number
  onSelect: (agentId: string) => void
  isSelected: boolean
}

export function AgentCard({ agent, onSelect, isSelected }: AgentCardProps) {
  // Display agent name and description directly from database
  const cardClass = isSelected
    ? "ring-2 ring-primary border-primary bg-primary/5"
    : "border hover:bg-accent/50"

  return (
    <Card
      className={`
        cursor-pointer transition-all duration-200 hover:shadow-md
        w-full
        ${cardClass}
      `}
      onClick={() => onSelect(agent.agent_id)}
    >
      <CardHeader className="pb-1 pt-3 px-3">
        <CardTitle className="text-sm font-semibold truncate">{agent.agent_id}</CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3 px-3">
        <CardDescription className="line-clamp-2 text-xs">
          {agent.description || ""}
        </CardDescription>
      </CardContent>
    </Card>
  )
}

interface AgentGridProps {
  agents: AgentInDB[]
  selectedAgentId: string
  onSelectAgent: (agentId: string) => void
}

export function AgentGrid({ agents, selectedAgentId, onSelectAgent }: AgentGridProps) {
  const { t } = useI18n()
  const [displayAgents, setDisplayAgents] = useState<AgentInDB[]>([])
  const [refreshKey, setRefreshKey] = useState(0)

  // Maximum agents displayed in sidebar (2 columns x 6 rows = 12, but limit to 8 for clean UI)
  const MAX_DISPLAY_COUNT = 8

  // Sort agents to ensure chatbot is always first
  const sortAgents = (agentsList: AgentInDB[]): AgentInDB[] => {
    return [...agentsList].sort((a, b) => {
      // chatbot always comes first
      if (a.agent_id === 'chatbot') return -1
      if (b.agent_id === 'chatbot') return 1
      // For other agents, maintain original order
      return 0
    })
  }

  useEffect(() => {
    // Sort agents with chatbot first, then select first batch or all if less
    const sortedAgents = sortAgents(agents)
    const initialAgents = sortedAgents.slice(0, MAX_DISPLAY_COUNT)
    setDisplayAgents(initialAgents)
  }, [agents])

  const handleShuffle = () => {
    if (agents.length <= MAX_DISPLAY_COUNT) {
      return
    }

    // Find chatbot and separate from other agents
    const chatbot = agents.find(a => a.agent_id === 'chatbot')
    const otherAgents = agents.filter(a => a.agent_id !== 'chatbot')

    // Randomly select from other agents
    const shuffled = [...otherAgents]
    // Fisher-Yates shuffle algorithm
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
        ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
    }

    // Reconstruct list with chatbot first (if it exists), then shuffle agents
    const result: AgentInDB[] = []
    if (chatbot) {
      result.push(chatbot)
    }
    // Add remaining agents up to MAX_DISPLAY_COUNT
    result.push(...shuffled.slice(0, MAX_DISPLAY_COUNT - result.length))

    setDisplayAgents(result)
    setRefreshKey(prev => prev + 1)
  }

  const showShuffleButton = agents.length > MAX_DISPLAY_COUNT

  // Single column layout for sidebar
  return (
    <div className="flex flex-col items-center gap-2 py-2 w-full">
      <div className="grid grid-cols-1 gap-2 w-full">
        {displayAgents.map((agent, index) => (
          <AgentCard
            key={`${agent.agent_id}-${refreshKey}-${index}`}
            agent={agent}
            index={index}
            onSelect={onSelectAgent}
            isSelected={selectedAgentId === agent.agent_id}
          />
        ))}
      </div>
      {showShuffleButton && (
        <div className="flex justify-center pt-1">
          <Button
            variant="outline"
            size="sm"
            onClick={handleShuffle}
            className="gap-1 h-7 text-xs w-full"
          >
            <Shuffle className="size-3" />
            {t("agent.shuffle")}
          </Button>
        </div>
      )}
    </div>
  )
}
