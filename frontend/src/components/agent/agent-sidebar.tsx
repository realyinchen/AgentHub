import { useState, useMemo } from "react"
import type { AgentInDB } from "@/types"
import { AgentSidebarCard } from "./agent-sidebar-card"
import { useI18n } from "@/i18n"

interface AgentSidebarProps {
  agents: AgentInDB[]
  selectedAgentId: string
  onSelectAgent: (agentId: string) => void
  hasMore?: boolean
  isLoadingMore?: boolean
  onLoadMore?: () => void
}

// Search component
function SearchInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { t } = useI18n()
  return (
    <div className="relative group px-1">
      <input
        type="text"
        placeholder={t("agent.search")}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full h-9 px-3 rounded-lg bg-white dark:bg-card border border-transparent
                   text-sm text-[#1d2129] dark:text-foreground placeholder:text-[#666666]/50 dark:placeholder:text-muted-foreground/50
                   transition-all duration-200 ease-out
                   focus:outline-none focus:border-[#ff6b00]/30 dark:focus:border-[var(--brand-accent)]/30 focus:bg-white dark:focus:bg-card
                   hover:bg-[#f5f7fa] dark:hover:bg-muted/50"
      />
    </div>
  )
}

export function AgentSidebar({
  agents,
  selectedAgentId,
  onSelectAgent,
  hasMore: hasMoreProp,
  isLoadingMore,
  onLoadMore,
}: AgentSidebarProps) {
  const { t } = useI18n()

  // Search state
  const [searchQuery, setSearchQuery] = useState("")

  // Sort agents to ensure chatbot is always first
  const sortedAgents = useMemo(() => {
    return [...agents].sort((a, b) => {
      // chatbot always comes first
      if (a.agent_id === 'chatbot') return -1
      if (b.agent_id === 'chatbot') return 1
      // For other agents, sort by agent_id
      return a.agent_id.localeCompare(b.agent_id)
    })
  }, [agents])

  // Filter agents by search query
  const filteredAgents = useMemo(() => {
    if (!searchQuery) return sortedAgents
    const query = searchQuery.toLowerCase()
    return sortedAgents.filter((agent) =>
      agent.agent_id.toLowerCase().includes(query) ||
      (agent.description || "").toLowerCase().includes(query)
    )
  }, [sortedAgents, searchQuery])

  // Use prop hasMore if provided (server-side pagination)
  const hasMore = hasMoreProp !== undefined ? hasMoreProp : false

  // Handle agent selection
  const handleSelectAgent = (agentId: string) => {
    onSelectAgent(agentId)
  }

  return (
    <div className="w-[240px] h-full bg-[#f5f7fa] dark:bg-muted/30 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="p-3 border-b border-[#e5e6eb] dark:border-border">
        <h3 className="text-sm font-semibold text-[#1d2129] dark:text-foreground px-1 mb-3">
          {t("agent.availableAgents")}
        </h3>
        <SearchInput value={searchQuery} onChange={setSearchQuery} />
      </div>

      {/* Agent List */}
      <div className="flex-1 overflow-y-auto p-2 sidebar-scroll-area">
        <div className="flex flex-col gap-2">
          {filteredAgents.map((agent) => (
            <AgentSidebarCard
              key={agent.agent_id}
              agent={agent}
              isSelected={selectedAgentId === agent.agent_id}
              onClick={() => handleSelectAgent(agent.agent_id)}
            />
          ))}
        </div>

        {/* Load more button */}
        {hasMore && onLoadMore && (
          <button
            onClick={onLoadMore}
            disabled={isLoadingMore}
            className="w-full mt-2 py-2 flex items-center justify-center
                       text-xs text-[#666666] dark:text-muted-foreground 
                       hover:text-[#1d2129] dark:hover:text-foreground
                       transition-colors duration-200
                       rounded-lg hover:bg-white/50 dark:hover:bg-card/50
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoadingMore ? (t("common.loading") || "Loading...") : t("common.loadMore")}
          </button>
        )}

        {/* Empty state */}
        {filteredAgents.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <p className="text-xs text-[#666666]/70 dark:text-muted-foreground/70">
              {searchQuery
                ? t("agent.noResults")
                : t("agent.none")}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
