import { useCallback, useEffect, useRef, useState, useMemo } from "react"

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
  ToolCallEvent,
  ToolCallInfo,
} from "@/types"
import { useThinkingMode } from "@/hooks/use-thinking-mode"
import {
  ChatMainPanel,
  ChatSidebar,
  ConversationRenameDialog,
  DeleteConversationDialog,
} from "@/features/chat/components"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import {
  getErrorMessage,
  isDefaultConversationTitle,
  normalizeChatMessage,
  readThreadIdFromUrl,
  sanitizeTitle,
  sortConversationsByUpdatedAt,
  toLocalMessage,
} from "@/features/chat/utils"

function readAgentIdFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search)
  return params.get("agent_id")
}
import { useI18n } from "@/i18n"

function App() {
  const { t } = useI18n()
  const defaultConversationTitle = t("conversation.defaultTitle")

  const [agents, setAgents] = useState<AgentInDB[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState("chatbot")

  const [conversations, setConversations] = useState<ConversationInDB[]>([])
  const [threadId, setThreadId] = useState("")
  
  // Thinking mode state - persisted per conversation in localStorage
  const {
    thinkingMode,
    toggleThinkingMode,
    isAvailable: isThinkingModeAvailable,
    isLoading: isThinkingModeLoading,
  } = useThinkingMode(threadId)
  const [conversationTitle, setConversationTitleState] = useState(
    defaultConversationTitle,
  )
  const [draftTitle, setDraftTitle] = useState(defaultConversationTitle)

  const [messages, setMessages] = useState<LocalChatMessage[]>([])

  const [appError, setAppError] = useState<string | null>(null)
  const [isInitializing, setIsInitializing] = useState(true)
  const [isLoadingConversation, setIsLoadingConversation] = useState(false)
  const [isSavingTitle, setIsSavingTitle] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isAwaitingAgentSelection, setIsAwaitingAgentSelection] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false) // 正在处理，尚未收到任何内容
  const [isAgentThinking, setIsAgentThinking] = useState(false)
  const [activeToolCall, setActiveToolCall] = useState<ToolCallEvent | null>(null)
  const [calledTools, setCalledTools] = useState<ToolCallInfo[]>([])
  const [thinkingContent, setThinkingContent] = useState("") // 累积的思考内容

  const [renameTarget, setRenameTarget] = useState<ConversationInDB | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ConversationInDB | null>(null)

  const abortControllerRef = useRef<AbortController | null>(null)
  const streamingPlaceholderIdRef = useRef<string | null>(null)
  const isProcessingRef = useRef(false)
  const thinkingModeRef = useRef(thinkingMode)
  
  // Keep thinkingModeRef in sync with thinkingMode state
  useEffect(() => {
    thinkingModeRef.current = thinkingMode
  }, [thinkingMode])

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
    async (targetThreadId: string, title: string, agentId?: string) => {
      const exists = conversations.some(
        (conversation) => conversation.thread_id === targetThreadId,
      )

      if (exists) {
        return
      }

      try {
        const created = await createConversation({
          thread_id: targetThreadId,
          title: sanitizeTitle(title) || defaultConversationTitle,
          agent_id: agentId || selectedAgentId,
        })

        setConversations((previous) =>
          sortConversationsByUpdatedAt([created, ...previous]),
        )
      } catch {
        await refreshConversations()
      }
    },
    [conversations, refreshConversations, selectedAgentId],
  )

  const openConversation = useCallback(
    async (
      targetThreadId: string,
      knownConversations: ConversationInDB[] = conversations,
      agentList: AgentInDB[] = agents,
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

      // Find the conversation to get its agent_id
      const conversation = knownConversations.find(
        (c) => c.thread_id === targetThreadId,
      )
      
      // Determine agent to use: prefer saved agent_id, fall back to default
      const defaultAgentId = agentList[0]?.agent_id ?? "chatbot"
      const savedAgentId = conversation?.agent_id
      const agentToUse = savedAgentId && agentList.some((a) => a.agent_id === savedAgentId)
        ? savedAgentId
        : defaultAgentId
      
      // Update selected agent if different
      setSelectedAgentId(agentToUse)

      try {
        const [historyResult, titleResult] = await Promise.allSettled([
          getHistory(agentToUse, targetThreadId),
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
            )?.title ?? defaultConversationTitle
          setConversationTitleState(fallbackTitle)
          setDraftTitle(fallbackTitle)
        }
      } catch (error) {
        setAppError(
          t("error.loadConversation", {
            details: getErrorMessage(error, t("error.unexpected")),
          }),
        )
        setMessages([])
        setConversationTitleState(defaultConversationTitle)
        setDraftTitle(defaultConversationTitle)
      } finally {
        setIsLoadingConversation(false)
      }
    },
    [agents, conversations, defaultConversationTitle, t, writeThreadIdToUrl],
  )

  const resetToNewConversation = useCallback(() => {
    abortControllerRef.current?.abort()
    setIsStreaming(false)

    const newThreadId = crypto.randomUUID()
    setThreadId(newThreadId)
    writeThreadIdToUrl(null)
    setMessages([])
    setConversationTitleState(defaultConversationTitle)
    setDraftTitle(defaultConversationTitle)
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
          const hasToolCalls = normalized.tool_calls && normalized.tool_calls.length > 0
          const hasContent = normalized.content && normalized.content.trim().length > 0
          
          // If we have a placeholder, update it with new content
          if (placeholderId) {
            // If this message has tool_calls, it means more content is coming
            // Update the placeholder but keep it alive for the final response
            if (hasToolCalls) {
              // Update placeholder with current content, but don't clear the ref
              return previous.map((item) =>
                item.local_id === placeholderId
                  ? {
                      ...item,
                      ...normalized,
                      local_id: placeholderId,
                      is_streaming: true,
                    }
                  : item,
              )
            }
            
            // If this message has content but no tool_calls, it's the final response
            // Update the placeholder and clear the ref
            if (hasContent) {
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
            
            // No content and no tool calls, keep placeholder as is
            return previous
          }

          // No placeholder - check for duplicates before adding new message
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
      if (!isDefaultConversationTitle(currentTitle) || !targetThreadId) {
        return
      }

      const titlePrompt = t("app.titlePrompt", { input: userInput })

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
    [t],
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

        // Reset state for new message
        setIsProcessing(true) // 开始处理，尚未收到任何内容
        isProcessingRef.current = true
        setIsAgentThinking(false)
        setCalledTools([])
        setThinkingContent("")

        // Use ref to get the latest thinkingMode value to avoid stale closure
        const currentThinkingMode = thinkingModeRef.current
        
        await streamChat(
          {
            content: trimmed,
            agent_id: selectedAgentId,
            thread_id: targetThreadId,
            thinking_mode: currentThinkingMode,
          },
          (event: StreamEvent) => {
            // 收到任何内容，停止显示"正在处理..."
            if (isProcessingRef.current) {
              setIsProcessing(false)
              isProcessingRef.current = false
            }

            if (event.type === "thinking") {
              // Thinking/reasoning content from models like DeepSeek-R1, Qwen3
              setIsAgentThinking(true)
              setActiveToolCall(null)
              // 累积思考内容
              setThinkingContent((prev) => prev + event.content)
              return
            }

            if (event.type === "token") {
              // When we start receiving tokens, agent is no longer "thinking"
              setIsAgentThinking(false)
              setActiveToolCall(null)
              addStreamToken(event.content)
              return
            }

            if (event.type === "message") {
              const message = event.content
              // When we receive an AI message with actual content (not just tool_calls), 
              // agent is no longer "thinking"
              if (message.type === "ai") {
                const hasContent = message.content && message.content.trim().length > 0
                const hasToolCalls = message.tool_calls && message.tool_calls.length > 0
                // Only stop thinking if we have content and no pending tool calls
                if (hasContent && !hasToolCalls) {
                  setIsAgentThinking(false)
                  setActiveToolCall(null)
                }
              }
              addMessageFromStream(message)
              return
            }

            if (event.type === "tool_call") {
              // Agent is calling a tool, show thinking state
              setIsAgentThinking(true)
              setActiveToolCall(event.content)
              // Add tool call info to list
              setCalledTools((prev) => {
                const existing = prev.find((t) => t.id === event.content.id)
                if (existing) {
                  return prev
                }
                return [
                  ...prev,
                  {
                    name: event.content.name,
                    id: event.content.id,
                    args: event.content.args || {},
                    status: "calling" as const,
                  },
                ]
              })
              return
            }

            if (event.type === "tool_result") {
              // Tool execution completed, update the tool call info
              setCalledTools((prev) =>
                prev.map((t) =>
                  t.id === event.content.id
                    ? { ...t, output: event.content.output, status: "completed" as const }
                    : t,
                ),
              )
              return
            }

            // error event
            setAppError(event.content)
            setMessages((previous) => [
              ...previous,
              toLocalMessage({
                type: "ai",
                content: t("error.streamPrefix", { details: event.content }),
              }),
            ])
          },
          controller.signal,
        )

        // Ensure all streaming placeholders are marked as complete
        setMessages((previous) =>
          previous.map((message) =>
            message.is_streaming
              ? { ...message, is_streaming: false }
              : message,
          ),
        )

        await refreshConversations()
        await maybeGenerateTitle(trimmed, targetThreadId, currentTitle)
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          const details = getErrorMessage(error, t("error.unexpected"))
          setAppError(t("error.generateResponse", { details }))
          setMessages((previous) => [
            ...previous,
            toLocalMessage({
              type: "ai",
              content: t("error.streamPrefix", { details }),
            }),
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
      t,
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
      setAppError(t("error.titleEmpty"))
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
      setAppError(
        t("error.updateTitle", {
          details: getErrorMessage(error, t("error.unexpected")),
        }),
      )
    } finally {
      setIsSavingTitle(false)
    }
  }, [
    draftTitle,
    ensureConversationExists,
    refreshConversations,
    renameTarget,
    t,
    threadId,
  ])

  const startRenameConversation = useCallback((conversation: ConversationInDB) => {
    setRenameTarget(conversation)
    setDraftTitle(sanitizeTitle(conversation.title) || defaultConversationTitle)
  }, [defaultConversationTitle])

  const confirmDeleteConversation = useCallback(async () => {
    if (!deleteTarget) {
      return
    }

    try {
      await setConversationTitle({
        thread_id: deleteTarget.thread_id,
        title: sanitizeTitle(deleteTarget.title) || t("conversation.untitled"),
        is_deleted: true,
      })

      setConversations((previous) =>
        previous.filter((item) => item.thread_id !== deleteTarget.thread_id),
      )

      if (deleteTarget.thread_id === threadId) {
        resetToNewConversation()
      }
    } catch (error) {
      setAppError(
        t("error.deleteConversation", {
          details: getErrorMessage(error, t("error.unexpected")),
        }),
      )
    } finally {
      setDeleteTarget(null)
    }
  }, [deleteTarget, resetToNewConversation, t, threadId])

  const handleRenameDialogChange = useCallback(
    (open: boolean) => {
      if (!open) {
        setRenameTarget(null)
        setDraftTitle(defaultConversationTitle)
      }
    },
    [defaultConversationTitle],
  )

  const handleRenameCancel = useCallback(() => {
    setRenameTarget(null)
    setDraftTitle(defaultConversationTitle)
  }, [defaultConversationTitle])

  const handleDeleteDialogChange = useCallback((open: boolean) => {
    if (!open) {
      setDeleteTarget(null)
    }
  }, [])

  useEffect(() => {
    setConversationTitleState((current) =>
      isDefaultConversationTitle(current) ? defaultConversationTitle : current,
    )
    setDraftTitle((current) =>
      isDefaultConversationTitle(current) ? defaultConversationTitle : current,
    )
  }, [defaultConversationTitle])

  // 使用 ref 存储 t 函数和 defaultConversationTitle，避免语言切换时重新初始化
  const tRef = useRef(t)
  const defaultConversationTitleRef = useRef(defaultConversationTitle)
  useEffect(() => {
    tRef.current = t
    defaultConversationTitleRef.current = defaultConversationTitle
  }, [t, defaultConversationTitle])

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

        const sorted = sortConversationsByUpdatedAt(conversationList)
        setConversations(sorted)

        const queryThreadId = readThreadIdFromUrl()
        const queryAgentId = readAgentIdFromUrl()

        // 如果 URL 中有 agent_id 参数，直接使用该 agent
        if (queryAgentId) {
          const validAgentId = agentList.some(
            (agent) => agent.agent_id === queryAgentId
          )
            ? queryAgentId
            : defaultAgentId
          setSelectedAgentId(validAgentId)
        } else {
          setSelectedAgentId(defaultAgentId)
        }

        if (queryThreadId) {
          setIsAwaitingAgentSelection(false)
          setThreadId(queryThreadId)
          writeThreadIdToUrl(queryThreadId)
          setIsLoadingConversation(true)

          // Find the conversation to get its saved agent_id
          const conversation = sorted.find(
            (c) => c.thread_id === queryThreadId,
          )
          const savedAgentId = conversation?.agent_id

          // Determine agent to use: URL param > saved agent_id > default
          let agentToUse = defaultAgentId
          if (queryAgentId && agentList.some((agent) => agent.agent_id === queryAgentId)) {
            agentToUse = queryAgentId
          } else if (savedAgentId && agentList.some((agent) => agent.agent_id === savedAgentId)) {
            agentToUse = savedAgentId
          }

          // Update selected agent
          setSelectedAgentId(agentToUse)

          const [historyResult, titleResult] = await Promise.allSettled([
            getHistory(agentToUse, queryThreadId),
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
              )?.title ?? defaultConversationTitle
            setConversationTitleState(fallbackTitle)
            setDraftTitle(fallbackTitle)
          }

          setIsLoadingConversation(false)
        } else {
          const newThreadId = crypto.randomUUID()
          setThreadId(newThreadId)
          setConversationTitleState(defaultConversationTitle)
          setDraftTitle(defaultConversationTitle)
          setMessages([])

          // 如果 URL 中有 agent_id，直接进入聊天界面，不需要选择 agent
          if (queryAgentId) {
            setIsAwaitingAgentSelection(false)
          } else {
            setIsAwaitingAgentSelection(true)
          }
          writeThreadIdToUrl(null)
        }
      } catch (error) {
        if (!cancelled) {
          setAppError(
            tRef.current("error.initApp", {
              details: getErrorMessage(error, tRef.current("error.unexpected")),
            }),
          )
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
              conversations,
              agents,
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
            isProcessing={isProcessing}
            isAgentThinking={isAgentThinking}
            activeToolCall={activeToolCall}
            calledTools={calledTools}
            thinkingContent={thinkingContent}
            messages={messages}
            onSendMessage={handleSendMessage}
            onStopStreaming={stopStreaming}
            onSelectAgent={pickAgentForCurrentConversation}
            thinkingMode={thinkingMode}
            onToggleThinkingMode={toggleThinkingMode}
            isThinkingModeAvailable={isThinkingModeAvailable}
            isThinkingModeLoading={isThinkingModeLoading}
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
