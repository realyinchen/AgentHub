import type { AgentInDB } from "@/types"

interface AgentSidebarCardProps {
  agent: AgentInDB
  isSelected: boolean
  onClick: () => void
}

export function AgentSidebarCard({ agent, isSelected, onClick }: AgentSidebarCardProps) {
  return (
    <div
      onClick={onClick}
      className={`
        group cursor-pointer rounded-[10px] p-[12px_14px]
        transition-all duration-200 ease-out
        bg-white dark:bg-card
        hover:bg-[#f5f7fa] dark:hover:bg-muted/50
        ${isSelected
          ? "border-l-[4px] border-l-[#ff6b00] dark:border-l-[var(--brand-accent)]"
          : "border-l-[4px] border-l-transparent"
        }
        ${isSelected ? "bg-[rgba(255,107,0,0.1)] dark:bg-[var(--brand-accent)]/10" : ""}
      `}
      style={{
        minHeight: "72px",
      }}
    >
      {/* 标题 */}
      <div
        className="text-[14px] font-semibold leading-[1.4] text-[#1d2129] dark:text-foreground"
        style={{
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {agent.agent_id}
      </div>

      {/* 描述 */}
      <div
        className="mt-[4px] text-[12px] font-normal leading-[1.4] text-[#666666] dark:text-muted-foreground"
        style={{
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {agent.description || ""}
      </div>
    </div>
  )
}
