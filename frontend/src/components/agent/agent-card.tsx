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
  const { t } = useI18n()

  const isRagAgent = agent.agent_id.toLowerCase().includes("rag")
  const isChatbotAgent = agent.agent_id === "chatbot"
  
  const displayName = isRagAgent
    ? t("chat.status.rag")
    : isChatbotAgent
      ? t("chat.status.chatbot")
      : agent.agent_id

  // RAG agent and chatbot agent cards use normal border style, other agents use highlighted border when selected
  const cardClass = isRagAgent || isChatbotAgent
    ? "border"
    : isSelected 
      ? "ring-2 ring-primary border-primary" 
      : "border"

  return (
    <Card
      className={`
        cursor-pointer transition-all duration-300 hover:scale-105 hover:shadow-lg
        ${cardClass}
      `}
      onClick={() => onSelect(agent.agent_id)}
    >
      <CardHeader className="pb-2">
        <CardTitle className="text-lg">{displayName}</CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <CardDescription className="line-clamp-3">
          {agent.description || t("agent.noDescription")}
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

  // Maximum 9 agents displayed (3x3 grid layout)
  const MAX_DISPLAY_COUNT = 9
  // const actualCount = Math.min(agents.length, MAX_DISPLAY_COUNT)

  useEffect(() => {
    // Initially select first 9 or all if less than 9
    const initialAgents = agents.slice(0, MAX_DISPLAY_COUNT)
    setDisplayAgents(initialAgents)
  }, [agents])

  const handleShuffle = () => {
    if (agents.length <= MAX_DISPLAY_COUNT) {
      return
    }

    // Randomly select 9 unique agents
    const shuffled = [...agents]
    // Fisher-Yates shuffle algorithm
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
    }
    setDisplayAgents(shuffled.slice(0, MAX_DISPLAY_COUNT))
    setRefreshKey(prev => prev + 1)
  }

  const showShuffleButton = agents.length > MAX_DISPLAY_COUNT

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="grid grid-cols-3 gap-4">
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
        <div className="flex justify-center pt-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleShuffle}
            className="gap-2"
          >
            <Shuffle className="size-4" />
            {t("agent.shuffle")}
          </Button>
        </div>
      )}
    </div>
  )
}
