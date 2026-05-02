import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { MessageSquare, ChevronLeft, ChevronRight } from "lucide-react"

import type { ConversationInDB } from "@/types"
import { formatUpdatedAt } from "@/features/chat/utils"
import { DARK_THEME } from "../styles/theme"

type ConversationGridProps = {
  refreshKey?: number
}

export function ConversationGrid({ refreshKey }: ConversationGridProps) {
  const navigate = useNavigate()
  const [conversations, setConversations] = useState<ConversationInDB[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [isLoading, setIsLoading] = useState(true)
  const pageSize = 8 // 2 columns × 4 rows

  useEffect(() => {
    const fetchConversations = async () => {
      setIsLoading(true)
      try {
        const offset = (page - 1) * pageSize
        const response = await fetch(`/api/v1/chat/conversations?limit=${pageSize}&offset=${offset}`)
        if (response.ok) {
          const data = await response.json()
          setConversations(data)
          const totalCount = response.headers.get("X-Total-Count")
          setTotal(totalCount ? parseInt(totalCount, 10) : 0)
        }
      } catch (error) {
        console.error("Failed to fetch conversations:", error)
      } finally {
        setIsLoading(false)
      }
    }

    fetchConversations()
  }, [page, refreshKey])

  const totalPages = Math.ceil(total / pageSize)

  const handleViewDetail = (threadId: string) => {
    navigate(`/kanban/${threadId}`)
  }

  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center h-64"
        style={{ color: DARK_THEME.textSecondary }}
      >
        Loading...
      </div>
    )
  }

  if (conversations.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center h-64"
        style={{ color: DARK_THEME.textDim }}
      >
        <MessageSquare className="w-12 h-12 mb-4 opacity-50" />
        <p>No conversations yet</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Card Grid */}
      <div className="grid grid-cols-2 gap-4">
        {conversations.map((conversation) => (
          <div
            key={conversation.thread_id}
            className="p-4 rounded-xl transition-all cursor-pointer group"
            style={{
              background: DARK_THEME.bgPanel,
              border: `1px solid ${DARK_THEME.border}`,
            }}
            onClick={() => handleViewDetail(conversation.thread_id)}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = DARK_THEME.borderActive
              e.currentTarget.style.transform = 'translateY(-2px)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = DARK_THEME.border
              e.currentTarget.style.transform = 'translateY(0)'
            }}
          >
            {/* Header */}
            <div className="flex items-center gap-2 min-w-0 mb-3">
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{
                  background: DARK_THEME.nodeAILight,
                  border: `1px solid ${DARK_THEME.border}`,
                }}
              >
                <MessageSquare className="w-4 h-4" style={{ color: DARK_THEME.nodeAI }} />
              </div>
              <h3
                className="font-medium truncate"
                style={{ color: DARK_THEME.textPrimary }}
              >
                {conversation.title || "Untitled Conversation"}
              </h3>
            </div>

            {/* Meta info */}
            <div
              className="flex items-center gap-3 text-xs mb-3"
              style={{ color: DARK_THEME.textDim }}
            >
              <span>{formatUpdatedAt(conversation.updated_at, 'zh')}</span>
              {conversation.agent_id && (
                <>
                  <span>·</span>
                  <span>{conversation.agent_id}</span>
                </>
              )}
            </div>

          </div>
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div
          className="flex items-center justify-between pt-4"
          style={{ borderTop: `1px solid ${DARK_THEME.border}` }}
        >
          <span
            className="text-sm"
            style={{ color: DARK_THEME.textDim }}
          >
            {total} total
          </span>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="w-8 h-8 flex items-center justify-center rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              style={{
                background: DARK_THEME.bgPanel,
                border: `1px solid ${DARK_THEME.border}`,
                color: DARK_THEME.textSecondary,
              }}
            >
              <ChevronLeft className="w-4 h-4" />
            </button>

            <div className="flex items-center gap-1">
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                let pageNum: number
                if (totalPages <= 5) {
                  pageNum = i + 1
                } else if (page <= 3) {
                  pageNum = i + 1
                } else if (page >= totalPages - 2) {
                  pageNum = totalPages - 4 + i
                } else {
                  pageNum = page - 2 + i
                }
                return (
                  <button
                    key={pageNum}
                    onClick={() => setPage(pageNum)}
                    className="w-8 h-8 flex items-center justify-center rounded-lg text-sm font-medium transition-colors cursor-pointer"
                    style={{
                      background: page === pageNum
                        ? DARK_THEME.nodeAI
                        : DARK_THEME.bgPanel,
                      border: `1px solid ${page === pageNum
                        ? DARK_THEME.borderActive
                        : DARK_THEME.border}`,
                      color: page === pageNum
                        ? '#fff'
                        : DARK_THEME.textSecondary,
                    }}
                  >
                    {pageNum}
                  </button>
                )
              })}
            </div>

            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="w-8 h-8 flex items-center justify-center rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              style={{
                background: DARK_THEME.bgPanel,
                border: `1px solid ${DARK_THEME.border}`,
                color: DARK_THEME.textSecondary,
              }}
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}