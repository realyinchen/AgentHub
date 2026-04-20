import { useState } from "react"
import { MessageSquarePlus, MoreHorizontal, PencilLine, Trash2, History, ChevronsLeft, ChevronsRight, ChevronsDown, Search } from "lucide-react"

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

// Search component
function SearchInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { t } = useI18n()
  return (
    <div className="relative group">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-sidebar-foreground/50 transition-colors group-focus-within:text-primary" />
      <input
        type="text"
        placeholder={t("conversation.search") || "Search conversations..."}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full h-9 pl-9 pr-3 rounded-xl bg-sidebar-accent/30 border border-transparent
                   text-sm text-sidebar-foreground placeholder:text-sidebar-foreground/40
                   transition-all duration-200 ease-out
                   focus:outline-none focus:border-primary/40 focus:bg-sidebar-accent/50
                   focus:shadow-[0_0_0_3px_rgba(0,209,255,0.1)]
                   dark:focus:shadow-[0_0_0_3px_rgba(0,209,255,0.15)]
                   hover:bg-sidebar-accent/40"
      />
    </div>
  )
}

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
  // Search state
  const [searchQuery, setSearchQuery] = useState("")

  // Filter conversations by search query
  const filteredConversations = searchQuery
    ? conversations.filter((c) =>
        c.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : conversations

  // Get visible conversations
  const visibleConversations = filteredConversations.slice(0, displayCount)
  const hasMore = filteredConversations.length > displayCount

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
            {/* Search input */}
            <div className="px-1 mb-3">
              <SearchInput value={searchQuery} onChange={setSearchQuery} />
            </div>
            
            {filteredConversations.length === 0 ? (
              <p className="mt-3 rounded-xl border border-dashed border-sidebar-border/50 p-4 text-sm text-sidebar-foreground/60 text-center">
                {searchQuery 
                  ? (t("conversation.noResults") || "No conversations found") 
                  : t("conversation.none")}
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
                          className={`h-auto items-start py-2.5 pr-10 cursor-pointer rounded-xl
                                     transition-all duration-200 ease-out
                                     ${isActive 
                                       ? 'bg-gradient-to-r from-warm/15 to-transparent border-l-2 border-warm pl-3 ml-0' 
                                       : 'hover:bg-sidebar-accent/50 hover:translate-x-0.5'}`}
                          onClick={() => onOpenConversation(conversation)}
                        >
                          <div className="min-w-0">
                            <p className={`line-clamp-1 text-sm transition-colors duration-200 ${isActive ? 'font-semibold text-sidebar-foreground' : 'font-medium text-sidebar-foreground/90'}`}>
                              {conversation.title}
                            </p>
                            <p className="text-xs text-sidebar-foreground/50 mt-0.5">
                              {formatUpdatedAt(conversation.updated_at, locale)}
                            </p>
                          </div>
                        </SidebarMenuButton>

                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="absolute top-2 cursor-pointer right-2 size-7 text-sidebar-foreground/50
                                         opacity-0 group-hover/item:opacity-100 transition-all duration-200
                                         hover:bg-sidebar-accent/80 hover:text-sidebar-foreground
                                         rounded-lg"
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