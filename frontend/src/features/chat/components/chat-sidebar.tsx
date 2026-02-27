import { MessageSquarePlus, MoreHorizontal, PencilLine, Trash2 } from "lucide-react"

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
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar"
import agentHubLogo from "@/assets/agenthub.png"

import { formatUpdatedAt } from "@/features/chat/utils"

type ChatSidebarProps = {
  threadId: string
  conversations: ConversationInDB[]
  onOpenConversation: (conversation: ConversationInDB) => void
  onRenameConversation: (conversation: ConversationInDB) => void
  onDeleteConversation: (conversation: ConversationInDB) => void
  onCreateConversation: () => void
  disableCreateConversation: boolean
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
  const { state } = useSidebar()
  const isCollapsed = state === "collapsed"

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader className={isCollapsed ? "gap-3 " : "gap-3 p-4"}>
        {isCollapsed ? (
          <div className="group/logo relative mx-auto flex size-9 items-center justify-center">
            <img
              src="/vite.svg"
              alt="Sidebar logo"
              className="size-7 transition-all duration-150 group-hover/logo:scale-90 group-hover/logo:opacity-0"
            />
            <SidebarTrigger className="absolute inset-0 size-9 scale-90 cursor-pointer rounded-md opacity-0 pointer-events-none transition-all duration-150 group-hover/logo:scale-100 group-hover/logo:opacity-100 group-hover/logo:pointer-events-auto" />
          </div>
        ) : (
          <div className="flex w-full items-center justify-between gap-3">
            <img src={agentHubLogo} alt="" className="h-9 w-auto" />
            <SidebarTrigger className="size-8 cursor-pointer rounded-md" />
          </div>
        )}
      </SidebarHeader>

      <SidebarSeparator />

      <SidebarContent className={isCollapsed ? " pb-3" : "px-1 pb-3"}>
        <SidebarGroup className="pt-2 mt-2">
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  className="cursor-pointer"
                  tooltip="新会话"
                  onClick={onCreateConversation}
                  disabled={disableCreateConversation}
                >
                  <MessageSquarePlus className="size-4" />
                  <span>新会话</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="pt-1 group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel className="px-2">Recent</SidebarGroupLabel>
          <SidebarGroupContent>
            {conversations.length === 0 ? (
              <p className="mt-3 rounded-lg border border-dashed p-3 text-sm text-sidebar-foreground/70">
                No saved conversations yet.
              </p>
            ) : (
              <SidebarMenu>
                {conversations.map((conversation) => {
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
                              {formatUpdatedAt(conversation.updated_at)}
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
                              aria-label="Conversation actions"
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
                              重命名
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              variant="destructive"
                              className="cursor-pointer"
                              onClick={() => onDeleteConversation(conversation)}
                            >
                              <Trash2 className="size-4" />
                              删除
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            )}
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  )
}
