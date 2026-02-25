import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Bot,
  LoaderCircle,
  MessageSquarePlus,
  PencilLine,
  Sparkles,
  Trash2,
  User,
} from "lucide-react"

import {
  createConversation,
  getConversationTitle,
  getHistory,
  invoke,
  listAgents,
  listConversations,
  setConversationTitle,
  streamChat,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import type {
  AgentInDB,
  ChatMessage,
  ConversationInDB,
  LocalChatMessage,
  StreamEvent,
} from "@/types"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import {
  ChatInput,
  ChatInputEditor,
  ChatInputGroupAddon,
  ChatInputGroupText,
  ChatInputSubmitButton,
  useChatInput,
} from "@/components/ui/chat-input"
import { MarkdownContent } from "@/components/ui/markdown-content"

const DEFAULT_CONVERSATION_TITLE = "New conversation"

function normalizeChatMessage(message: Partial<ChatMessage>): ChatMessage {
  const toolCalls = Array.isArray(message.tool_calls)
    ? message.tool_calls.map((call) => ({
        id: String(call.id ?? crypto.randomUUID()),
        name: String(call.name ?? "tool"),
        args:
          call.args && typeof call.args === "object"
            ? (call.args as Record<string, unknown>)
            : {},
        type: call.type,
      }))
    : []

  return {
    type: (message.type as ChatMessage["type"]) ?? "ai",
    content: typeof message.content === "string" ? message.content : "",
    tool_calls: toolCalls,
    tool_call_id: message.tool_call_id ?? null,
    run_id: message.run_id ?? null,
    response_metadata:
      message.response_metadata && typeof message.response_metadata === "object"
        ? (message.response_metadata as Record<string, unknown>)
        : {},
    custom_data:
      message.custom_data && typeof message.custom_data === "object"
        ? (message.custom_data as Record<string, unknown>)
        : {},
  }
}

function toLocalMessage(
  message: Partial<ChatMessage>,
  options?: { localId?: string; isStreaming?: boolean },
): LocalChatMessage {
  const normalized = normalizeChatMessage(message)
  return {
    ...normalized,
    local_id: options?.localId ?? crypto.randomUUID(),
    is_streaming: options?.isStreaming,
  }
}

function sortConversationsByUpdatedAt(
  items: ConversationInDB[],
): ConversationInDB[] {
  return [...items].sort(
    (a, b) =>
      new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  )
}

function sanitizeTitle(rawTitle: string): string {
  return rawTitle.trim().replace(/\s+/g, " ").slice(0, 64)
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message
  }
  return "Unexpected error"
}

function formatUpdatedAt(isoString: string): string {
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) {
    return ""
  }

  return date.toLocaleString([], {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function readThreadIdFromUrl(): string | null {
  const value = new URLSearchParams(window.location.search).get("thread_id")
  return value && value.trim() ? value : null
}

function App() {
  const [agents, setAgents] = useState<AgentInDB[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState("chatbot")

  const [conversations, setConversations] = useState<ConversationInDB[]>([])
  const [threadId, setThreadId] = useState("")
  const [conversationTitle, setConversationTitleState] = useState(
    DEFAULT_CONVERSATION_TITLE,
  )
  const [draftTitle, setDraftTitle] = useState(DEFAULT_CONVERSATION_TITLE)

  const [messages, setMessages] = useState<LocalChatMessage[]>([])

  const [appError, setAppError] = useState<string | null>(null)
  const [isInitializing, setIsInitializing] = useState(true)
  const [isLoadingConversation, setIsLoadingConversation] = useState(false)
  const [isSavingTitle, setIsSavingTitle] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)

  const [isRenameDialogOpen, setIsRenameDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ConversationInDB | null>(null)

  const abortControllerRef = useRef<AbortController | null>(null)
  const streamingPlaceholderIdRef = useRef<string | null>(null)
  const endOfMessagesRef = useRef<HTMLDivElement | null>(null)

  const activeAgentIds = useMemo(
    () => agents.map((item) => item.agent_id),
    [agents],
  )

  const writeThreadIdToUrl = useCallback((nextThreadId: string | null) => {
    const url = new URL(window.location.href)
    if (nextThreadId) {
      url.searchParams.set("thread_id", nextThreadId)
    } else {
      url.searchParams.delete("thread_id")
    }
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`)
  }, [])

  const refreshConversations = useCallback(async () => {
    const latest = await listConversations(100)
    setConversations(sortConversationsByUpdatedAt(latest))
  }, [])

  const ensureConversationExists = useCallback(
    async (targetThreadId: string, title: string) => {
      const exists = conversations.some(
        (conversation) => conversation.thread_id === targetThreadId,
      )

      if (exists) {
        return
      }

      try {
        const created = await createConversation({
          thread_id: targetThreadId,
          title: sanitizeTitle(title) || DEFAULT_CONVERSATION_TITLE,
        })

        setConversations((previous) =>
          sortConversationsByUpdatedAt([created, ...previous]),
        )
      } catch {
        await refreshConversations()
      }
    },
    [conversations, refreshConversations],
  )

  const openConversation = useCallback(
    async (
      targetThreadId: string,
      agentId: string,
      knownConversations: ConversationInDB[] = conversations,
    ) => {
      if (!targetThreadId) {
        return
      }

      abortControllerRef.current?.abort()
      setIsStreaming(false)
      setThreadId(targetThreadId)
      writeThreadIdToUrl(targetThreadId)
      setIsRenameDialogOpen(false)
      setIsLoadingConversation(true)
      setAppError(null)

      try {
        const [historyResult, titleResult] = await Promise.allSettled([
          getHistory(agentId, targetThreadId),
          getConversationTitle(targetThreadId),
        ])

        if (historyResult.status === "fulfilled") {
          setMessages(
            historyResult.value.messages.map((message) => toLocalMessage(message)),
          )
        } else {
          setMessages([])
        }

        if (titleResult.status === "fulfilled" && titleResult.value?.title) {
          const normalized = sanitizeTitle(titleResult.value.title)
          setConversationTitleState(normalized)
          setDraftTitle(normalized)
        } else {
          const fallbackTitle =
            knownConversations.find(
              (conversation) => conversation.thread_id === targetThreadId,
            )?.title ?? DEFAULT_CONVERSATION_TITLE
          setConversationTitleState(fallbackTitle)
          setDraftTitle(fallbackTitle)
        }
      } catch (error) {
        setAppError(`Failed to load conversation: ${getErrorMessage(error)}`)
        setMessages([])
        setConversationTitleState(DEFAULT_CONVERSATION_TITLE)
        setDraftTitle(DEFAULT_CONVERSATION_TITLE)
      } finally {
        setIsLoadingConversation(false)
      }
    },
    [conversations, writeThreadIdToUrl],
  )

  const resetToNewConversation = useCallback(() => {
    abortControllerRef.current?.abort()
    setIsStreaming(false)

    const newThreadId = crypto.randomUUID()
    setThreadId(newThreadId)
    writeThreadIdToUrl(null)
    setMessages([])
    setConversationTitleState(DEFAULT_CONVERSATION_TITLE)
    setDraftTitle(DEFAULT_CONVERSATION_TITLE)
    setIsRenameDialogOpen(false)
    setAppError(null)
  }, [writeThreadIdToUrl])

  const addStreamToken = useCallback((token: string) => {
    if (!token) {
      return
    }

    setMessages((previous) => {
      let placeholderId = streamingPlaceholderIdRef.current

      if (!placeholderId) {
        placeholderId = crypto.randomUUID()
        streamingPlaceholderIdRef.current = placeholderId

        return [
          ...previous,
          toLocalMessage(
            {
              type: "ai",
              content: token,
            },
            { localId: placeholderId, isStreaming: true },
          ),
        ]
      }

      return previous.map((message) =>
        message.local_id === placeholderId
          ? { ...message, content: `${message.content}${token}`, is_streaming: true }
          : message,
      )
    })
  }, [])

  const addMessageFromStream = useCallback(
    (message: ChatMessage, sentText: string) => {
      const normalized = normalizeChatMessage(message)

      if (normalized.type === "human" && normalized.content === sentText) {
        return
      }

      setMessages((previous) => {
        if (normalized.type === "ai") {
          const placeholderId = streamingPlaceholderIdRef.current
          if (placeholderId && normalized.content) {
            streamingPlaceholderIdRef.current = null
            return previous.map((item) =>
              item.local_id === placeholderId
                ? {
                    ...item,
                    ...normalized,
                    local_id: placeholderId,
                    is_streaming: false,
                  }
                : item,
            )
          }
        }

        if (
          normalized.type === "ai" &&
          !normalized.content &&
          !normalized.tool_calls.length
        ) {
          return previous
        }

        return [...previous, toLocalMessage(normalized)]
      })
    },
    [],
  )

  const stopStreaming = useCallback(() => {
    abortControllerRef.current?.abort()
    setIsStreaming(false)
  }, [])

  const maybeGenerateTitle = useCallback(
    async (userInput: string, targetThreadId: string, currentTitle: string) => {
      if (currentTitle !== DEFAULT_CONVERSATION_TITLE || !targetThreadId) {
        return
      }

      const titlePrompt =
        "Generate a concise title under 50 characters for this conversation. " +
        `First user message: ${userInput}`

      try {
        const titleResponse = await invoke({
          content: titlePrompt,
          agent_id: "chatbot",
        })

        const generatedTitle = sanitizeTitle(
          titleResponse.content.replace(/(^['"]|['"]$)/g, ""),
        )

        if (!generatedTitle) {
          return
        }

        const updated = await setConversationTitle({
          thread_id: targetThreadId,
          title: generatedTitle,
          is_deleted: false,
        })

        setConversationTitleState(generatedTitle)
        setDraftTitle(generatedTitle)

        if (updated) {
          setConversations((previous) => {
            const next = previous.filter(
              (conversation) => conversation.thread_id !== updated.thread_id,
            )
            return sortConversationsByUpdatedAt([updated, ...next])
          })
        }
      } catch {
        // Title generation should never block the main chat flow.
      }
    },
    [],
  )

  const handleSendMessage = useCallback(
    async (rawInput: string) => {
      const trimmed = rawInput.trim()
      if (!trimmed || !threadId || !selectedAgentId || isStreaming) {
        return
      }

      setAppError(null)
      setMessages((previous) => [
        ...previous,
        toLocalMessage({ type: "human", content: trimmed }),
      ])

      const targetThreadId = threadId
      const currentTitle = conversationTitle

      try {
        await ensureConversationExists(targetThreadId, currentTitle)

        setIsStreaming(true)
        streamingPlaceholderIdRef.current = null

        const controller = new AbortController()
        abortControllerRef.current = controller

        await streamChat(
          {
            content: trimmed,
            agent_id: selectedAgentId,
            thread_id: targetThreadId,
          },
          (event: StreamEvent) => {
            if (event.type === "token") {
              addStreamToken(event.content)
              return
            }

            if (event.type === "message") {
              addMessageFromStream(event.content, trimmed)
              return
            }

            setAppError(event.content)
            setMessages((previous) => [
              ...previous,
              toLocalMessage({ type: "ai", content: `Error: ${event.content}` }),
            ])
          },
          controller.signal,
        )

        setMessages((previous) =>
          previous.map((message) =>
            message.local_id === streamingPlaceholderIdRef.current
              ? { ...message, is_streaming: false }
              : message,
          ),
        )

        await refreshConversations()
        await maybeGenerateTitle(trimmed, targetThreadId, currentTitle)
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          const details = getErrorMessage(error)
          setAppError(`Failed to generate response: ${details}`)
          setMessages((previous) => [
            ...previous,
            toLocalMessage({ type: "ai", content: `Error: ${details}` }),
          ])
        }
      } finally {
        setIsStreaming(false)
        streamingPlaceholderIdRef.current = null
        abortControllerRef.current = null
      }
    },
    [
      addMessageFromStream,
      addStreamToken,
      conversationTitle,
      ensureConversationExists,
      isStreaming,
      maybeGenerateTitle,
      refreshConversations,
      selectedAgentId,
      threadId,
    ],
  )

  const composer = useChatInput({
    onSubmit: (parsedValue) => {
      void handleSendMessage(parsedValue.content)
    },
  })

  const handleSaveTitle = useCallback(async () => {
    if (!threadId) {
      return
    }

    const nextTitle = sanitizeTitle(draftTitle)
    if (!nextTitle) {
      setAppError("Title cannot be empty")
      return
    }

    setIsSavingTitle(true)
    setAppError(null)

    try {
      await ensureConversationExists(threadId, nextTitle)

      const updated = await setConversationTitle({
        thread_id: threadId,
        title: nextTitle,
        is_deleted: false,
      })

      setConversationTitleState(nextTitle)
      setDraftTitle(nextTitle)
      setIsRenameDialogOpen(false)

      if (updated) {
        setConversations((previous) => {
          const next = previous.filter(
            (conversation) => conversation.thread_id !== updated.thread_id,
          )
          return sortConversationsByUpdatedAt([updated, ...next])
        })
      } else {
        await refreshConversations()
      }
    } catch (error) {
      setAppError(`Failed to update title: ${getErrorMessage(error)}`)
    } finally {
      setIsSavingTitle(false)
    }
  }, [draftTitle, ensureConversationExists, refreshConversations, threadId])

  const confirmDeleteConversation = useCallback(async () => {
    if (!deleteTarget) {
      return
    }

    try {
      await setConversationTitle({
        thread_id: deleteTarget.thread_id,
        title: sanitizeTitle(deleteTarget.title) || "Untitled",
        is_deleted: true,
      })

      setConversations((previous) =>
        previous.filter((item) => item.thread_id !== deleteTarget.thread_id),
      )

      if (deleteTarget.thread_id === threadId) {
        resetToNewConversation()
      }
    } catch (error) {
      setAppError(`Failed to delete conversation: ${getErrorMessage(error)}`)
    } finally {
      setDeleteTarget(null)
    }
  }, [deleteTarget, resetToNewConversation, threadId])

  useEffect(() => {
    endOfMessagesRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, isStreaming, isLoadingConversation])

  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      setIsInitializing(true)
      setAppError(null)

      try {
        const [agentList, conversationList] = await Promise.all([
          listAgents(),
          listConversations(100),
        ])

        if (cancelled) {
          return
        }

        setAgents(agentList)
        const defaultAgentId = agentList[0]?.agent_id ?? "chatbot"
        setSelectedAgentId(defaultAgentId)

        const sorted = sortConversationsByUpdatedAt(conversationList)
        setConversations(sorted)

        const queryThreadId = readThreadIdFromUrl()
        if (queryThreadId) {
          setThreadId(queryThreadId)
          writeThreadIdToUrl(queryThreadId)
          setIsLoadingConversation(true)

          const [historyResult, titleResult] = await Promise.allSettled([
            getHistory(defaultAgentId, queryThreadId),
            getConversationTitle(queryThreadId),
          ])

          if (historyResult.status === "fulfilled") {
            setMessages(
              historyResult.value.messages.map((message) => toLocalMessage(message)),
            )
          } else {
            setMessages([])
          }

          if (titleResult.status === "fulfilled" && titleResult.value?.title) {
            const normalized = sanitizeTitle(titleResult.value.title)
            setConversationTitleState(normalized)
            setDraftTitle(normalized)
          } else {
            const fallbackTitle =
              sorted.find(
                (conversation) => conversation.thread_id === queryThreadId,
              )?.title ?? DEFAULT_CONVERSATION_TITLE
            setConversationTitleState(fallbackTitle)
            setDraftTitle(fallbackTitle)
          }

          setIsLoadingConversation(false)
        } else {
          const newThreadId = crypto.randomUUID()
          setThreadId(newThreadId)
          setConversationTitleState(DEFAULT_CONVERSATION_TITLE)
          setDraftTitle(DEFAULT_CONVERSATION_TITLE)
          setMessages([])
          writeThreadIdToUrl(null)
        }
      } catch (error) {
        if (!cancelled) {
          setAppError(`Failed to initialize app: ${getErrorMessage(error)}`)
        }
      } finally {
        if (!cancelled) {
          setIsLoadingConversation(false)
          setIsInitializing(false)
        }
      }
    }

    void bootstrap()

    return () => {
      cancelled = true
      abortControllerRef.current?.abort()
    }
  }, [writeThreadIdToUrl])

  return (
    <>
      <div className="mx-auto grid min-h-screen max-w-[1440px] grid-cols-1 gap-4 p-4 md:grid-cols-[330px_minmax(0,1fr)]">
        <Card className="flex h-[calc(100vh-2rem)] flex-col overflow-hidden border-border/70">
          <CardHeader className="space-y-4 pb-4">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Sparkles className="size-4" />
              </div>
              <div>
                <CardTitle className="text-lg">Agent Hub</CardTitle>
                <CardDescription>FastAPI + shadcn/ui + simple-ai</CardDescription>
              </div>
            </div>

            <div className="space-y-3">
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Agent
                </p>
                <Select
                  value={selectedAgentId}
                  onValueChange={setSelectedAgentId}
                  disabled={isInitializing || activeAgentIds.length === 0}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select an agent" />
                  </SelectTrigger>
                  <SelectContent>
                    {activeAgentIds.length === 0 ? (
                      <SelectItem value="chatbot">chatbot</SelectItem>
                    ) : (
                      activeAgentIds.map((agentId) => (
                        <SelectItem key={agentId} value={agentId}>
                          {agentId}
                        </SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
              </div>

              <Button
                className="w-full justify-start"
                onClick={resetToNewConversation}
                disabled={isInitializing}
              >
                <MessageSquarePlus className="mr-2 size-4" />
                New conversation
              </Button>
            </div>
          </CardHeader>

          <Separator />

          <CardContent className="flex min-h-0 flex-1 flex-col gap-4 pt-4">
            <div className="flex items-center justify-between gap-2">
              <div className="space-y-1">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Current title
                </p>
                <p className="line-clamp-1 text-sm font-medium">{conversationTitle}</p>
              </div>
              <Button
                variant="outline"
                size="icon"
                onClick={() => setIsRenameDialogOpen(true)}
                disabled={!threadId}
              >
                <PencilLine className="size-4" />
              </Button>
            </div>

            <Separator />

            <div className="flex min-h-0 flex-1 flex-col gap-2">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Recent
              </p>

              <ScrollArea className="h-full pr-3">
                <div className="space-y-2 pb-2">
                  {conversations.length === 0 ? (
                    <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                      No saved conversations yet.
                    </p>
                  ) : (
                    conversations.map((conversation) => {
                      const isActive = conversation.thread_id === threadId

                      return (
                        <div
                          key={conversation.thread_id}
                          className={cn(
                            "rounded-md border p-1",
                            isActive
                              ? "border-primary/60 bg-primary/5"
                              : "border-border/70",
                          )}
                        >
                          <div className="flex items-center gap-1">
                            <Button
                              variant="ghost"
                              className="h-auto flex-1 justify-start px-2 py-2"
                              onClick={() =>
                                void openConversation(
                                  conversation.thread_id,
                                  selectedAgentId,
                                  conversations,
                                )
                              }
                            >
                              <div className="w-full text-left">
                                <p className="line-clamp-1 text-sm font-medium">
                                  {conversation.title}
                                </p>
                                <p className="text-xs text-muted-foreground">
                                  {formatUpdatedAt(conversation.updated_at)}
                                </p>
                              </div>
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="text-muted-foreground hover:text-destructive"
                              onClick={() => setDeleteTarget(conversation)}
                              aria-label="Delete conversation"
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>
              </ScrollArea>
            </div>
          </CardContent>
        </Card>

        <Card className="flex h-[calc(100vh-2rem)] flex-col overflow-hidden border-border/70">
          <CardHeader className="pb-4">
            <div className="flex items-center justify-between gap-3">
              <div className="space-y-1">
                <CardTitle className="line-clamp-1 text-lg">{conversationTitle}</CardTitle>
                <CardDescription>
                  <Badge variant="secondary" className="font-normal">
                    {selectedAgentId || "No agent"}
                  </Badge>
                </CardDescription>
              </div>

              {isStreaming ? (
                <Badge className="gap-1 bg-primary/15 text-primary hover:bg-primary/20">
                  <LoaderCircle className="size-3 animate-spin" />
                  Streaming
                </Badge>
              ) : null}
            </div>
          </CardHeader>

          <CardContent className="flex min-h-0 flex-1 flex-col gap-4">
            {appError ? (
              <Alert variant="destructive">
                <AlertTitle>Request failed</AlertTitle>
                <AlertDescription>{appError}</AlertDescription>
              </Alert>
            ) : null}

            {isLoadingConversation ? (
              <div className="space-y-3">
                <Skeleton className="h-16 w-2/3" />
                <Skeleton className="ml-auto h-14 w-1/2" />
                <Skeleton className="h-18 w-3/4" />
              </div>
            ) : (
              <ScrollArea className="h-full pr-4">
                <div className="space-y-4 pb-2">
                  {messages.length === 0 ? (
                    <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                      Welcome to AgentHub. Start a conversation with your selected agent.
                    </div>
                  ) : (
                    messages.map((message) => {
                      const isUser = message.type === "human"
                      const isAI = message.type === "ai"

                      return (
                        <article
                          key={message.local_id}
                          className={cn(
                            "flex w-full items-start gap-3",
                            isUser && "justify-end",
                          )}
                        >
                          {!isUser ? (
                            <Avatar className="mt-1 size-8 border border-border">
                              <AvatarFallback className="bg-muted text-muted-foreground">
                                <Bot className="size-4" />
                              </AvatarFallback>
                            </Avatar>
                          ) : null}

                          <Card
                            className={cn(
                              "max-w-[85%] border-border/70",
                              isUser &&
                                "bg-primary text-primary-foreground shadow-none",
                            )}
                          >
                            <CardContent className="space-y-3 p-3">
                              {isAI ? (
                                message.content ? (
                                  <MarkdownContent content={message.content} />
                                ) : message.is_streaming ? (
                                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                    <LoaderCircle className="size-4 animate-spin" />
                                    Thinking...
                                  </div>
                                ) : (
                                  <p className="text-sm text-muted-foreground">
                                    No visible output.
                                  </p>
                                )
                              ) : (
                                <p className="whitespace-pre-wrap break-words text-sm leading-6">
                                  {message.content || "No visible output."}
                                </p>
                              )}

                              {message.tool_calls.length > 0 ? (
                                <div className="space-y-2">
                                  {message.tool_calls.map((call) => (
                                    <Card key={call.id} className="bg-muted/50">
                                      <CardContent className="space-y-2 p-3">
                                        <div className="flex items-center gap-2">
                                          <Badge variant="outline">Tool</Badge>
                                          <span className="text-xs font-medium">
                                            {call.name}
                                          </span>
                                        </div>
                                        <pre className="overflow-x-auto rounded-md bg-background p-2 text-xs">
                                          {JSON.stringify(call.args, null, 2)}
                                        </pre>
                                      </CardContent>
                                    </Card>
                                  ))}
                                </div>
                              ) : null}

                              {message.type === "tool" ? (
                                <Badge variant="secondary" className="font-normal">
                                  tool call id: {message.tool_call_id || "unknown"}
                                </Badge>
                              ) : null}
                            </CardContent>
                          </Card>

                          {isUser ? (
                            <Avatar className="mt-1 size-8 border border-border">
                              <AvatarFallback className="bg-primary/10 text-primary">
                                <User className="size-4" />
                              </AvatarFallback>
                            </Avatar>
                          ) : null}
                        </article>
                      )
                    })
                  )}
                  <div ref={endOfMessagesRef} />
                </div>
              </ScrollArea>
            )}
          </CardContent>

          <Separator />

          <CardFooter className="pt-4">
            <ChatInput
              className="w-full"
              onSubmit={composer.handleSubmit}
              value={composer.value}
              onChange={composer.onChange}
              isStreaming={isStreaming}
              onStop={stopStreaming}
              disabled={isInitializing || isLoadingConversation}
            >
              <ChatInputEditor placeholder="Type your message here..." />
              <ChatInputGroupAddon align="block-end">
                <ChatInputGroupText>{selectedAgentId || "chatbot"}</ChatInputGroupText>
                <ChatInputSubmitButton className="ml-auto" />
              </ChatInputGroupAddon>
            </ChatInput>
          </CardFooter>
        </Card>
      </div>

      <Dialog
        open={isRenameDialogOpen}
        onOpenChange={(open) => {
          setIsRenameDialogOpen(open)
          if (!open) {
            setDraftTitle(conversationTitle)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit conversation title</DialogTitle>
            <DialogDescription>
              Update the current conversation title (max 64 characters).
            </DialogDescription>
          </DialogHeader>

          <Input
            value={draftTitle}
            onChange={(event) => setDraftTitle(event.target.value)}
            maxLength={64}
            placeholder="Conversation title"
          />

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setDraftTitle(conversationTitle)
                setIsRenameDialogOpen(false)
              }}
            >
              Cancel
            </Button>
            <Button onClick={() => void handleSaveTitle()} disabled={isSavingTitle}>
              {isSavingTitle ? (
                <>
                  <LoaderCircle className="mr-2 size-4 animate-spin" />
                  Saving
                </>
              ) : (
                "Save"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null)
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              This action marks the conversation as deleted and removes it from your
              recent list.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void confirmDeleteConversation()}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

export default App
