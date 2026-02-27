import { useCallback, useEffect, useRef, useState } from "react"

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
import type {
  AgentInDB,
  ChatMessage,
  ConversationInDB,
  LocalChatMessage,
  StreamEvent,
} from "@/types"
import {
  ChatMainPanel,
  ChatSidebar,
  ConversationRenameDialog,
  DeleteConversationDialog,
} from "@/features/chat/components"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import {
  DEFAULT_CONVERSATION_TITLE,
  getErrorMessage,
  normalizeChatMessage,
  readThreadIdFromUrl,
  sanitizeTitle,
  sortConversationsByUpdatedAt,
  toLocalMessage,
} from "@/features/chat/utils"

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
  const [isAwaitingAgentSelection, setIsAwaitingAgentSelection] = useState(false)

  const [renameTarget, setRenameTarget] = useState<ConversationInDB | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ConversationInDB | null>(null)

  const abortControllerRef = useRef<AbortController | null>(null)
  const streamingPlaceholderIdRef = useRef<string | null>(null)

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
      setIsAwaitingAgentSelection(false)
      setThreadId(targetThreadId)
      writeThreadIdToUrl(targetThreadId)
      setRenameTarget(null)
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
    setRenameTarget(null)
    setIsAwaitingAgentSelection(true)
    setAppError(null)
  }, [writeThreadIdToUrl])

  const pickAgentForCurrentConversation = useCallback((agentId: string) => {
    setSelectedAgentId(agentId)
    setIsAwaitingAgentSelection(false)
    setAppError(null)
  }, [])

  const createStreamingPlaceholder = useCallback(() => {
    const placeholderId = crypto.randomUUID()
    streamingPlaceholderIdRef.current = placeholderId

    setMessages((previous) => [
      ...previous,
      toLocalMessage(
        {
          type: "ai",
          content: "",
        },
        { localId: placeholderId, isStreaming: true },
      ),
    ])
  }, [])

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
    (message: ChatMessage) => {
      const normalized = normalizeChatMessage(message)

      // The UI already appends the user's text immediately.
      if (normalized.type === "human") {
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

          const duplicatedByRunId =
            normalized.run_id &&
            previous.some(
              (item) =>
                item.type === "ai" &&
                item.run_id === normalized.run_id &&
                item.content === normalized.content,
            )

          const lastMessage = previous[previous.length - 1]
          const duplicatedByContent =
            !normalized.run_id &&
            lastMessage?.type === "ai" &&
            lastMessage.content === normalized.content &&
            normalized.content.length > 0

          if (duplicatedByRunId || duplicatedByContent) {
            return previous
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
      if (
        !trimmed ||
        !threadId ||
        !selectedAgentId ||
        isStreaming ||
        isAwaitingAgentSelection
      ) {
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
        createStreamingPlaceholder()

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
              addMessageFromStream(event.content)
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
      createStreamingPlaceholder,
      ensureConversationExists,
      isAwaitingAgentSelection,
      isStreaming,
      maybeGenerateTitle,
      refreshConversations,
      selectedAgentId,
      threadId,
    ],
  )

  const handleSaveTitle = useCallback(async () => {
    const targetThreadId = renameTarget?.thread_id ?? threadId
    if (!targetThreadId) {
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
      await ensureConversationExists(targetThreadId, nextTitle)

      const updated = await setConversationTitle({
        thread_id: targetThreadId,
        title: nextTitle,
        is_deleted: false,
      })

      if (targetThreadId === threadId) {
        setConversationTitleState(nextTitle)
      }
      setDraftTitle(nextTitle)
      setRenameTarget(null)

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
  }, [draftTitle, ensureConversationExists, refreshConversations, renameTarget, threadId])

  const startRenameConversation = useCallback((conversation: ConversationInDB) => {
    setRenameTarget(conversation)
    setDraftTitle(sanitizeTitle(conversation.title) || DEFAULT_CONVERSATION_TITLE)
  }, [])

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

  const handleRenameDialogChange = useCallback(
    (open: boolean) => {
      if (!open) {
        setRenameTarget(null)
        setDraftTitle(DEFAULT_CONVERSATION_TITLE)
      }
    },
    [],
  )

  const handleRenameCancel = useCallback(() => {
    setRenameTarget(null)
    setDraftTitle(DEFAULT_CONVERSATION_TITLE)
  }, [])

  const handleDeleteDialogChange = useCallback((open: boolean) => {
    if (!open) {
      setDeleteTarget(null)
    }
  }, [])

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
          setIsAwaitingAgentSelection(false)
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
          setIsAwaitingAgentSelection(true)
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
      <SidebarProvider defaultOpen className="h-screen overflow-hidden">
        <ChatSidebar
          threadId={threadId}
          conversations={conversations}
          onCreateConversation={resetToNewConversation}
          disableCreateConversation={isInitializing || isLoadingConversation}
          onOpenConversation={(conversation) => {
            void openConversation(
              conversation.thread_id,
              selectedAgentId,
              conversations,
            )
          }}
          onRenameConversation={startRenameConversation}
          onDeleteConversation={setDeleteTarget}
        />

        <SidebarInset className="min-h-0 overflow-hidden bg-background">
          <ChatMainPanel
            agents={agents}
            selectedAgentId={selectedAgentId}
            appError={appError}
            isStreaming={isStreaming}
            isInitializing={isInitializing}
            isLoadingConversation={isLoadingConversation}
            isAwaitingAgentSelection={isAwaitingAgentSelection}
            messages={messages}
            onSendMessage={handleSendMessage}
            onStopStreaming={stopStreaming}
            onSelectAgent={pickAgentForCurrentConversation}
          />
        </SidebarInset>
      </SidebarProvider>

      <ConversationRenameDialog
        open={Boolean(renameTarget)}
        draftTitle={draftTitle}
        isSavingTitle={isSavingTitle}
        onOpenChange={handleRenameDialogChange}
        onDraftTitleChange={setDraftTitle}
        onCancel={handleRenameCancel}
        onSave={() => {
          void handleSaveTitle()
        }}
      />

      <DeleteConversationDialog
        open={Boolean(deleteTarget)}
        title={deleteTarget?.title}
        onOpenChange={handleDeleteDialogChange}
        onConfirm={() => {
          void confirmDeleteConversation()
        }}
      />
    </>
  )
}

export default App
