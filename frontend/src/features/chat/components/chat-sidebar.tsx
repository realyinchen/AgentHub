import { MoreHorizontal, PencilLine, Trash2 } from "lucide-react"

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
} from "@/components/ui/sidebar"
import agentHubLogo from "@/assets/agenthub.png"

import { formatUpdatedAt } from "@/features/chat/utils"

type ChatSidebarProps = {
  threadId: string
  conversations: ConversationInDB[]
  onOpenConversation: (conversation: ConversationInDB) => void
  onRenameConversation: (conversation: ConversationInDB) => void
  onDeleteConversation: (conversation: ConversationInDB) => void
}

export function ChatSidebar({
  threadId,
  conversations,
  onOpenConversation,
  onRenameConversation,
  onDeleteConversation,
}: ChatSidebarProps) {
  return (
    <Sidebar collapsible="offcanvas" variant="sidebar">
      <SidebarHeader className="gap-3 p-4">
        <div className="flex items-center justify-center">
          <img src={agentHubLogo} alt="" className="h-9 w-auto" />
        </div>
      </SidebarHeader>

      <SidebarSeparator />

      <SidebarContent className="px-2 pb-3">
        <SidebarGroup className="pt-2">
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
