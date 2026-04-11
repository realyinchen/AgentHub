import { useState } from "react"
import { MessageSquarePlus, MoreHorizontal, PencilLine, Trash2, History, ChevronsLeft, ChevronsRight, ChevronsDown } from "lucide-react"

import type { ConversationInDB } from "@/types"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
  useSidebar,
} from "@/components/ui/sidebar"
import agentHubLogo from "@/assets/agenthub.png"

import { formatUpdatedAt } from "@/features/chat/utils"
import { useI18n } from "@/i18n"

type ChatSidebarProps = {
  threadId: string
  conversations: ConversationInDB[]
  onOpenConversation: (conversation: ConversationInDB) => void
  onRenameConversation: (conversation: ConversationInDB) => void
  onDeleteConversation: (conversation: ConversationInDB) => void
  onCreateConversation: () => void
  disableCreateConversation: boolean
}

// Pagination constants
const INITIAL_DISPLAY_COUNT = 10
const LOAD_MORE_COUNT = 10

export function ChatSidebar({
  threadId,
  conversations,
  onOpenConversation,
  onRenameConversation,
  onDeleteConversation,
  onCreateConversation,
  disableCreateConversation,
}: ChatSidebarProps) {
  const { locale, t } = useI18n()
  const { state, toggleSidebar } = useSidebar()
  const isCollapsed = state === "collapsed"

  // Pagination state
  const [displayCount, setDisplayCount] = useState(INITIAL_DISPLAY_COUNT)

  // Get visible conversations
  const visibleConversations = conversations.slice(0, displayCount)
  const hasMore = conversations.length > displayCount

  // Load more conversations
  const loadMore = () => {
    setDisplayCount(prev => prev + LOAD_MORE_COUNT)
  }

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader className={isCollapsed ? "gap-2" : "gap-2 p-3"}>
        {isCollapsed ? (
          <div className="flex items-center justify-center py-2">
            <button
              onClick={() => toggleSidebar()}
              title={t("sidebar.expand") || "Expand sidebar"}
              className="size-8 flex items-center justify-center transition-all duration-150 hover:scale-90 cursor-pointer"
            >
              <div className="size-8 rounded-lg bg-primary flex items-center justify-center text-primary-foreground font-bold text-sm">
                <span className="text-[#FFB800]">A</span><span>H</span>
              </div>
            </button>
          </div>
        ) : (
          <div className="flex w-full items-center justify-between gap-3">
            <a
              href="/"
              title={t("sidebar.logoAlt")}
              className="flex items-center"
            >
              <img src={agentHubLogo} alt="" className="h-9 w-auto cursor-pointer" />
            </a>
            {/* Collapse button with << arrow */}
            <Button
              variant="ghost"
              size="icon"
              className="size-8 cursor-pointer rounded-md"
              onClick={() => toggleSidebar()}
              title={t("sidebar.collapse") || "Collapse sidebar"}
            >
              <ChevronsLeft className="size-4" />
            </Button>
          </div>
        )}
      </SidebarHeader>

      <SidebarSeparator />

      <SidebarContent className={isCollapsed ? "pb-3" : "px-1 pb-3"}>
        <SidebarGroup className="pt-2 mt-2">
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  className="cursor-pointer"
                  tooltip={t("conversation.new")}
                  onClick={onCreateConversation}
                  disabled={disableCreateConversation}
                >
                  <MessageSquarePlus className="size-4" />
                  <span>{t("conversation.new")}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              {/* Recent history icon when collapsed - below new conversation */}
              {isCollapsed && (
                <SidebarMenuItem>
                  <SidebarMenuButton
                    className="cursor-pointer"
                    tooltip={t("conversation.recent")}
                    onClick={() => toggleSidebar()}
                  >
                    <History className="size-4" />
                    <span>{t("conversation.recent")}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="pt-1 group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel className="px-2">{t("conversation.recent")}</SidebarGroupLabel>
          <SidebarGroupContent>
            {conversations.length === 0 ? (
              <p className="mt-3 rounded-lg border border-dashed p-3 text-sm text-sidebar-foreground/70">
                {t("conversation.none")}
              </p>
            ) : (
              <SidebarMenu>
                {visibleConversations.map((conversation) => {
                  const isActive = conversation.thread_id === threadId

                  return (
                    <SidebarMenuItem key={conversation.thread_id}>
                      <div className="group/item relative">
                        <SidebarMenuButton
                          isActive={isActive}
                          className="h-auto items-start py-2 pr-10 cursor-pointer"
                          onClick={() => onOpenConversation(conversation)}
                        >
                          <div className="min-w-0">
                            <p className="line-clamp-1 text-sm font-medium">
                              {conversation.title}
                            </p>
                            <p className="text-xs text-sidebar-foreground/60">
                              {formatUpdatedAt(conversation.updated_at, locale)}
                            </p>
                          </div>
                        </SidebarMenuButton>

                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="absolute top-1.5 cursor-pointer right-1 size-7 text-sidebar-foreground/65"
                              onClick={(event) => {
                                event.stopPropagation()
                              }}
                              aria-label={t("conversation.actions")}
                            >
                              <MoreHorizontal className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-36">
                            <DropdownMenuItem
                              className="cursor-pointer"
                              onClick={() => onRenameConversation(conversation)}
                            >
                              <PencilLine className="size-4" />
                              {t("common.rename")}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              variant="destructive"
                              className="cursor-pointer"
                              onClick={() => onDeleteConversation(conversation)}
                            >
                              <Trash2 className="size-4" />
                              {t("common.delete")}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </SidebarMenuItem>
                  )
                })}

                {/* Load more button */}
                {hasMore && (
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      className="cursor-pointer justify-center"
                      onClick={loadMore}
                    >
                      <ChevronsDown className="size-5" />
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )}
              </SidebarMenu>
            )}
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Expand button when collapsed - at the bottom */}
        {isCollapsed && (
          <SidebarGroup className="mt-auto pt-2">
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    className="cursor-pointer"
                    tooltip={t("sidebar.expand") || "Expand sidebar"}
                    onClick={() => toggleSidebar()}
                  >
                    <ChevronsRight className="size-4" />
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>
    </Sidebar>
  )
}