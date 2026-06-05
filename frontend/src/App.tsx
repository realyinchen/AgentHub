import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Languages, Moon, Share2, Sun, Settings } from "lucide-react"

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

import {
  createConversation,
  deleteConversation,
  generateTitle,
  getConversationTitle,
  getCurrentUserId,
  getHistory,
  listConversations,
  loadMoreConversations,
  setConversationTitle,
  setCurrentUserId,
  streamChat,
} from "@/lib/api"
import type {
  ChatMessage,
  ConversationInDB,
  LocalChatMessage,
  StreamEvent,
  ToolCallEvent,
  ToolCallInfo,
  UserInfo,
} from "@/types"
import { useThinkingMode } from "@/hooks/use-thinking-mode"
import { useTheme } from "@/hooks/use-theme"
import { useModels } from "@/hooks/use-models"
import { useUser } from "@/hooks/use-user"
import { useAuth } from "@/contexts/AuthContext"
import {
  ChatMainPanel,
  ChatSidebar,
  ConversationRenameDialog,
  DeleteConversationDialog,
  ShareDialog,
  TokenStatsPanel,
  TurnDAGSidebar,
} from "@/features/chat/components"
import { ProviderConfigDialog } from "@/features/chat/components/provider-config-dialog"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Button } from "@/components/ui/button"
import {
  getErrorMessage,
  isDefaultConversationTitle,
  normalizeChatMessage,
  readThreadIdFromUrl,
  writeToUrl,
  sanitizeTitle,
  sortConversationsByUpdatedAt,
  toLocalMessage,
} from "@/features/chat/utils"

import { useI18n } from "@/i18n"
import { HomePage } from "@/pages/home-page"
import { Toaster } from "@/components/ui/toaster"

function App() {
  const { t, toggleLocale } = useI18n()
  const { theme, toggleTheme } = useTheme()
  const defaultConversationTitle = t("conversation.defaultTitle")

  const [conversations, setConversations] = useState<ConversationInDB[]>([])
  const [threadId, setThreadId] = useState("")
  // Pagination state for conversations
  const [conversationsOffset, setConversationsOffset] = useState(0)
  const [hasMoreConversations, setHasMoreConversations] = useState(false)
  const [isLoadingMoreConversations, setIsLoadingMoreConversations] = useState(false)

  // User selection state (for Jack/Rose mock users)
  const { userId, currentUser, setUserId } = useUser()

  // Auth context (for WeChat login)
  const { user: authUser, isAuthenticated, isLoading: isAuthLoading, logout } = useAuth()

  // Determine if user is logged in (either via mock user or WeChat)
  // Priority: URL userId > mock userId > AuthContext
  const effectiveUserId = userId || (authUser?.id) || null
  const isLoggedIn = !!effectiveUserId || isAuthenticated

  // Thinking mode state - persisted per conversation in localStorage
  const {
    thinkingMode,
    setThinkingMode,
  } = useThinkingMode(threadId)

  // Model selection state - persisted per conversation in localStorage
  const {
    models,
    setSelectedModel,
    getEffectiveModel,
    getSelectedModelInfo,
    refreshModels,
  } = useModels(threadId, isLoggedIn)

  // Handle user switch - go back to home page
  const handleSwitchUser = useCallback(async () => {
    // Clear all conversation-related state to prevent data leakage between users
    setConversations([])
    setThreadId("")
    setMessages([])
    setConversationTitleState(defaultConversationTitle)
    setDraftTitle(defaultConversationTitle)
    setConversationsOffset(0)
    setHasMoreConversations(false)
    setSelectedRequestId(null)
    setAppError(null)
    abortControllerRef.current?.abort()
    setIsStreaming(false)

    setUserId(null)
    setCurrentUserId(null)
    // Call AuthContext logout to properly clear auth state (for WeChat users)
    await logout()
  }, [setUserId, logout, defaultConversationTitle])

  // Track if we need to re-initialize after user login
  const [needsReinit, setNeedsReinit] = useState(false)

  // Get the effective model ID (selected or default)
  const effectiveSelectedModel = getEffectiveModel()

  // Auto-sync thinking mode when model changes
  // If the selected model has thinking enabled, automatically turn on thinking mode
  useEffect(() => {
    const selectedModelInfo = getSelectedModelInfo()
    if (selectedModelInfo?.thinking) {
      setThinkingMode(true)
    }
  }, [effectiveSelectedModel, getSelectedModelInfo, setThinkingMode])

  // Get current model info to check if it supports thinking
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
  const [isProcessing, setIsProcessing] = useState(false) // Processing, no content received yet
  const [isAgentThinking, setIsAgentThinking] = useState(false)
  const [, setActiveToolCall] = useState<ToolCallEvent | null>(null)
  const [calledTools, setCalledTools] = useState<ToolCallInfo[]>([])
  const [thinkingContent, setThinkingContent] = useState("") // Accumulated thinking content

  // Toggle for showing/hiding the sidebar process panel
  const [showSidebarProcess, setShowSidebarProcess] = useState(true)

  // Selected request_id for viewing historical DAG
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null)



  const [renameTarget, setRenameTarget] = useState<ConversationInDB | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ConversationInDB | null>(null)
  const [showShareDialog, setShowShareDialog] = useState(false)
  const [showProviderConfig, setShowProviderConfig] = useState(false)
  const [showNoModelDialog, setShowNoModelDialog] = useState(false)

  const abortControllerRef = useRef<AbortController | null>(null)
  const streamingPlaceholderIdRef = useRef<string | null>(null)
  const currentRequestIdRef = useRef<string | null>(null)
  const isProcessingRef = useRef(false)
  const thinkingModeRef = useRef(thinkingMode)
  const effectiveModelRef = useRef<string | null>(null)

  // Keep refs in sync with state
  useEffect(() => {
    thinkingModeRef.current = thinkingMode
  }, [thinkingMode])

  useEffect(() => {
    effectiveModelRef.current = effectiveSelectedModel
  }, [effectiveSelectedModel])

  // Check if there are available models (active LLM/VLM)
  const hasAvailableModels = useMemo(() => {
    return models.some(m =>
      (m.model_type === "llm" || m.model_type === "vlm") &&
      m.is_active
    )
  }, [models])

  // Show dialog when no models are available after initialization
  useEffect(() => {
    if (!isInitializing && !isLoadingConversation) {
      // Show dialog when no models are configured (including when models array is empty)
      if (!hasAvailableModels) {
        setShowNoModelDialog(true)
      }
    }
  }, [isInitializing, isLoadingConversation, hasAvailableModels])

  // Write userId and threadId to URL
  // Use effectiveUserId to support both mock users and WeChat users
  const writeUrl = useCallback((nextThreadId: string | null) => {
    writeToUrl(effectiveUserId, nextThreadId)
  }, [effectiveUserId])

  const refreshConversations = useCallback(async () => {
    const { conversations: latest, total } = await listConversations(10, 0)
    setConversations(sortConversationsByUpdatedAt(latest))
    setConversationsOffset(latest.length)
    setHasMoreConversations(latest.length < total)
  }, [])

  const handleLoadMoreConversations = useCallback(async () => {
    if (isLoadingMoreConversations || !hasMoreConversations) {
      return
    }

    setIsLoadingMoreConversations(true)
    try {
      const { conversations: moreConversations, total } = await loadMoreConversations(
        conversationsOffset,
        10
      )

      if (moreConversations.length > 0) {
        setConversations((prev) => {
          // Remove duplicates based on thread_id
          const existingIds = new Set(prev.map((c) => c.thread_id))
          const uniqueNew = moreConversations.filter((c) => !existingIds.has(c.thread_id))
          return sortConversationsByUpdatedAt([...prev, ...uniqueNew])
        })
        setConversationsOffset((prev) => {
          const newOffset = prev + moreConversations.length
          // Use functional update to ensure we have the latest offset
          setHasMoreConversations(newOffset < total)
          return newOffset
        })
      } else {
        setHasMoreConversations(false)
      }
    } catch (error) {
      console.error("Failed to load more conversations:", error)
    } finally {
      setIsLoadingMoreConversations(false)
    }
  }, [conversationsOffset, hasMoreConversations, isLoadingMoreConversations])

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
          title: sanitizeTitle(title) || defaultConversationTitle,
        })

        setConversations((previous) =>
          sortConversationsByUpdatedAt([created, ...previous]),
        )
      } catch {
        await refreshConversations()
      }
    },
    [conversations, refreshConversations, defaultConversationTitle],
  )

  const openConversation = useCallback(
    async (
      targetThreadId: string,
      knownConversations: ConversationInDB[] = conversations,
    ) => {
      if (!targetThreadId) {
        return
      }

      abortControllerRef.current?.abort()
      setIsStreaming(false)
      setThreadId(targetThreadId)
      writeUrl(targetThreadId)
      setRenameTarget(null)
      setIsLoadingConversation(true)
      setAppError(null)

      try {
        const [historyResult, titleResult] = await Promise.allSettled([
          getHistory(targetThreadId),
          getConversationTitle(targetThreadId),
        ])

        if (historyResult.status === "fulfilled") {
          setMessages(
            historyResult.value.messages.map((message) => toLocalMessage(message)),
          )
          // Auto-select the latest request_id (from last AI message)
          const lastAiMessage = historyResult.value.messages
            .filter((m: ChatMessage) => m.type === "ai")
            .pop()
          if (lastAiMessage?.request_id) {
            setSelectedRequestId(lastAiMessage.request_id)
          } else {
            setSelectedRequestId(null)
          }
        } else {
          setMessages([])
          setSelectedRequestId(null)
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
    [conversations, defaultConversationTitle, t, writeUrl],
  )

  const resetToNewConversation = useCallback(() => {
    abortControllerRef.current?.abort()
    setIsStreaming(false)

    // Delay thread_id creation until first message is sent
    setThreadId("")
    writeUrl(null)
    setMessages([])
    setConversationTitleState(defaultConversationTitle)
    setDraftTitle(defaultConversationTitle)
    setRenameTarget(null)
    setAppError(null)
    setSelectedRequestId(null)
  }, [writeUrl, defaultConversationTitle])

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
            const existingItem = previous.find(item => item.local_id === placeholderId)
            const existingContent = existingItem?.content || ""
            const existingToolCalls = existingItem?.tool_calls || []

            // Backend sends both 'token' events (streaming) and 'message' events (complete)
            // Check if content was already streamed via token events
            // If existing content matches or is a prefix of the new content, tokens were already added
            const contentAlreadyStreamed = hasContent &&
              existingContent.length > 0 &&
              (normalized.content === existingContent ||
                normalized.content.startsWith(existingContent))

            // Determine final content:
            // - If content was already streamed via tokens, keep existing content
            // - Otherwise, use the message content (for non-streaming cases like tool calls)
            const finalContent = contentAlreadyStreamed ? existingContent :
              (hasContent ? normalized.content : existingContent)

            // Merge tool calls: combine existing and new (avoid duplicates by id)
            const mergedToolCalls = hasToolCalls
              ? [...existingToolCalls, ...normalized.tool_calls.filter(
                (newTc) => !existingToolCalls.some((existingTc) => existingTc.id === newTc.id)
              )]
              : existingToolCalls

            // Determine if this is the final response
            // Final response: has content AND no tool calls
            const isFinalResponse = hasContent && !hasToolCalls

            // Update the placeholder
            // Don't clear the ref during streaming - let the streaming end handler clear it
            return previous.map((item) =>
              item.local_id === placeholderId
                ? {
                  ...item,
                  content: finalContent,
                  tool_calls: mergedToolCalls,
                  custom_data: {
                    ...item.custom_data,
                    ...(normalized.custom_data?.thinking ? { thinking: normalized.custom_data.thinking } : {}),
                  },
                  local_id: placeholderId,
                  is_streaming: !isFinalResponse,
                }
                : item,
            )
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

          // If streaming is still in progress and the last message is an AI message,
          // merge the content instead of creating a new bubble.
          // This handles cases where the backend sends multiple intermediate messages
          // (e.g., "Let me check..." followed by the actual response).
          // We merge regardless of whether the last message is still marked as streaming,
          // as long as the overall streaming session is still active.
          const shouldMergeContent = isStreaming && lastMessage?.type === "ai" && hasContent

          if (shouldMergeContent) {
            // Merge content and tool calls into the last message
            const mergedContent = (lastMessage.content || "") + (normalized.content || "")
            const mergedToolCalls = [
              ...(lastMessage.tool_calls || []),
              ...(normalized.tool_calls || []),
            ]
            const mergedThinking = normalized.custom_data?.thinking || lastMessage.custom_data?.thinking
            // Keep request_id from either the existing message or the new normalized message
            const mergedRequestId = normalized.request_id || lastMessage.request_id

            return previous.map((item, index) => {
              if (index === previous.length - 1) {
                return {
                  ...item,
                  content: mergedContent,
                  tool_calls: mergedToolCalls,
                  request_id: mergedRequestId,
                  custom_data: {
                    ...item.custom_data,
                    ...(mergedThinking ? { thinking: mergedThinking } : {}),
                  },
                  // Keep streaming state - will be marked as complete when streaming ends
                  is_streaming: true,
                }
              }
              return item
            })
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
    [isStreaming],
  )

  const stopStreaming = useCallback(() => {
    abortControllerRef.current?.abort()
    setIsStreaming(false)
  }, [])

  const maybeGenerateTitle = useCallback(
    (
      userInput: string,
      aiResponse: string,
      targetThreadId: string,
      currentTitle: string,
    ) => {
      // Non-blocking title generation - fire and forget
      // This runs in the background without blocking user interaction
      if (!isDefaultConversationTitle(currentTitle) || !targetThreadId) {
        return
      }

      // Use void to explicitly mark as fire-and-forget
      void (async () => {
        try {
          // Use the lightweight title generation endpoint
          const result = await generateTitle({
            thread_id: targetThreadId,
            user_message: userInput,
            ai_response: aiResponse,
          })

          const generatedTitle = sanitizeTitle(result.title)

          if (!generatedTitle) {
            return
          }

          const updated = await setConversationTitle(
            targetThreadId,
            generatedTitle,
          )

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
          // Silently fail - user won't notice
        }
      })()
    },
    [],
  )

  const handleSendMessage = useCallback(
    async (rawInput: string, quotedMessageId?: string, userContent?: string) => {
      const trimmed = rawInput.trim()
      if (
        !trimmed ||
        isStreaming
      ) {
        return
      }

      // Lazy create thread_id if this is a brand new conversation
      let targetThreadId = threadId
      if (!targetThreadId) {
        targetThreadId = crypto.randomUUID()
        setThreadId(targetThreadId)
      }

      setAppError(null)
      setSelectedRequestId(null) // Reset to show latest request after streaming ends
      setMessages((previous) => [
        ...previous,
        toLocalMessage(
          { type: "human", content: trimmed },
          {
            customData: quotedMessageId ? {
              quoted_message_id: quotedMessageId,
              user_content: userContent,
            } : undefined
          }
        ),
      ])

      const currentTitle = conversationTitle

      try {
        await ensureConversationExists(targetThreadId, currentTitle)

        // Write thread_id to URL for sharing (especially important for new conversations)
        writeUrl(targetThreadId)

        setIsStreaming(true)
        streamingPlaceholderIdRef.current = null
        createStreamingPlaceholder()

        const controller = new AbortController()
        abortControllerRef.current = controller

        // Reset state for new message
        setIsProcessing(true) // Start processing, no content received yet
        isProcessingRef.current = true
        setIsAgentThinking(false)
        setCalledTools([])
        setThinkingContent("")

        // Use ref to get the latest thinkingMode and model value to avoid stale closure
        const currentThinkingMode = thinkingModeRef.current
        const currentModel = effectiveModelRef.current

        await streamChat(
          {
            content: trimmed,
            thread_id: targetThreadId,
            user_id: getCurrentUserId() || "default",
            request_id: crypto.randomUUID(),
            model_name: currentModel,
            thinking_mode: currentThinkingMode,
            custom_data: quotedMessageId ? {
              quoted_message_id: quotedMessageId,
              user_content: userContent,
            } : undefined,
          },
          (event: StreamEvent) => {
            // Handle request_start event - store request_id for DAG viewing
            if (event.type === "request_start") {
              currentRequestIdRef.current = event.request_id
              // Update the placeholder message with request_id
              const placeholderId = streamingPlaceholderIdRef.current
              if (placeholderId) {
                setMessages((previous) =>
                  previous.map((item) =>
                    item.local_id === placeholderId
                      ? { ...item, request_id: event.request_id }
                      : item,
                  ),
                )
              }
              return
            }

            if (event.type === "llm" || event.type === "reasoning") {
              // Thinking/reasoning content from models like DeepSeek-R1, Qwen3
              // "llm" is legacy event type, "reasoning" is LangChain v3 streaming type
              // Stop showing "processing..." loader when reasoning content arrives
              if (isProcessingRef.current) {
                setIsProcessing(false)
                isProcessingRef.current = false
              }
              setIsAgentThinking(true)
              setActiveToolCall(null)
              // Accumulate thinking content
              setThinkingContent((prev) => prev + event.content)
              return
            }

            if (event.type === "token") {
              // When we start receiving tokens, agent is no longer "thinking"
              // Also stop showing "processing..." loader since content is now arriving
              if (isProcessingRef.current) {
                setIsProcessing(false)
                isProcessingRef.current = false
              }
              setIsAgentThinking(false)
              setActiveToolCall(null)
              addStreamToken(event.content)
              return
            }

            if (event.type === "message") {
              const message = event.content
              // Stop loading animation when we receive a message event
              // This handles cases where backend sends message directly without streaming tokens
              if (isProcessingRef.current) {
                setIsProcessing(false)
                isProcessingRef.current = false
              }
              // When we receive an AI message with actual content (not just tool_calls), 
              // agent is no longer "thinking"
              if (message.type === "ai") {
                const hasContent = message.content && message.content.trim().length > 0
                const hasToolCalls = message.tool_calls && message.tool_calls.length > 0

                // If this is an intermediate message (has tool_calls but no meaningful content),
                // don't add it to messages - just track tool calls
                if (hasToolCalls && !hasContent) {
                  // This is an intermediate AI message for tool calls
                  // Don't add to messages array - tool info is already tracked via calledTools
                  return
                }

                // Only stop thinking if we have content and no pending tool calls
                if (hasContent && !hasToolCalls) {
                  setIsAgentThinking(false)
                  setActiveToolCall(null)
                }
              }
              addMessageFromStream(message)
              return
            }

            if (event.type === "tool") {
              // Agent is calling a tool - stop showing "processing..." loader
              // Content is arriving (tool call is a form of content)
              if (isProcessingRef.current) {
                setIsProcessing(false)
                isProcessingRef.current = false
              }
              setIsAgentThinking(true)
              // Create ToolCallEvent from the new event format
              const toolCallEvent: ToolCallEvent = {
                name: event.content.name,
                id: event.content.tool_id,
                args: event.content.args,
              }
              setActiveToolCall(toolCallEvent)
              // Add tool call info to list
              setCalledTools((prev) => {
                const existing = prev.find((t) => t.id === event.content.tool_id)
                if (existing) {
                  return prev
                }
                return [
                  ...prev,
                  {
                    name: event.content.name,
                    id: event.content.tool_id,
                    args: event.content.args || {},
                    status: "calling" as const,
                  },
                ]
              })
              return
            }

            if (event.type === "tool_result") {
              // Tool execution completed, update the tool call info
              // Still keep isProcessing true - more tools may be called or AI response pending
              setCalledTools((prev) =>
                prev.map((t) =>
                  t.id === event.content.id
                    ? { ...t, output: event.content.output, status: "completed" as const }
                    : t,
                ),
              )
              return
            }

            if (event.type === "usage") {
              // Token usage event from backend - log for debugging
              const usage = event.content.usage
              console.log(
                `[${event.content.node}] Token usage:`,
                `input=${usage.input_tokens ?? 'N/A'}, output=${usage.output_tokens ?? 'N/A'},`,
                `total=${usage.total_tokens ?? 'N/A'}`
              )
              return
            }

            // error event - TypeScript knows this must be { type: "error"; content: string }
            if (event.type === "error") {
              setAppError(event.content)
              setMessages((previous) => [
                ...previous,
                toLocalMessage({
                  type: "ai",
                  content: t("error.streamPrefix", { details: event.content }),
                }),
              ])
            }
          },
          controller.signal,
        )

        await refreshConversations()

        // Get the last AI message content for title generation
        // Use a callback to get the latest messages state
        let lastAiContent = ""
        setMessages((previous) => {
          for (let i = previous.length - 1; i >= 0; i--) {
            if (previous[i].type === "ai" && previous[i].content) {
              lastAiContent = previous[i].content
              break
            }
          }
          return previous
        })

        // Non-blocking title generation - fire and forget
        // User can continue chatting while title is being generated
        maybeGenerateTitle(trimmed, lastAiContent, targetThreadId, currentTitle)
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

        // Auto-select the latest request_id from messages
        setMessages((currentMessages) => {
          const lastAiMessage = currentMessages.filter(m => m.type === "ai" && m.request_id).pop()
          if (lastAiMessage?.request_id) {
            setSelectedRequestId(lastAiMessage.request_id)
          }
          return currentMessages
        })
      }
    },
    [
      addMessageFromStream,
      addStreamToken,
      conversationTitle,
      createStreamingPlaceholder,
      ensureConversationExists,
      isStreaming,
      maybeGenerateTitle,
      refreshConversations,
      t,
      threadId,
      writeUrl,
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

      const updated = await setConversationTitle(targetThreadId, nextTitle)

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
      await deleteConversation(deleteTarget.thread_id)

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

  // Jump to specified message
  const jumpToMessage = useCallback((localId: string) => {
    const element = document.getElementById(`message-${localId}`)
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "center" })
      // Add highlight effect
      element.classList.add("ring-2", "ring-primary/50", "rounded-lg")
      setTimeout(() => {
        element.classList.remove("ring-2", "ring-primary/50", "rounded-lg")
      }, 2000)
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

  // Use ref to store t function and defaultConversationTitle to avoid re-initialization on language switch
  const tRef = useRef(t)
  const defaultConversationTitleRef = useRef(defaultConversationTitle)
  useEffect(() => {
    tRef.current = t
    defaultConversationTitleRef.current = defaultConversationTitle
  }, [t, defaultConversationTitle])

  useEffect(() => {
    // Only run bootstrap after user logs in
    if (!isLoggedIn) {
      return
    }

    let cancelled = false

    async function bootstrap() {
      setIsInitializing(true)
      setAppError(null)

      try {
        const conversationResult = await listConversations(10, 0)

        if (cancelled) {
          return
        }

        const conversationList = conversationResult.conversations
        const total = conversationResult.total
        const sorted = sortConversationsByUpdatedAt(conversationList)
        // Always replace conversations to prevent data leakage between users.
        // When switching users, handleSwitchUser already clears conversations,
        // but we use replace here as a safety net.
        setConversations(sorted)
        // Update pagination state based on first load
        setConversationsOffset(sorted.length)
        setHasMoreConversations(sorted.length < total)

        const queryThreadId = readThreadIdFromUrl()

        if (queryThreadId) {
          setThreadId(queryThreadId)
          writeUrl(queryThreadId)
          setIsLoadingConversation(true)

          const [historyResult, titleResult] = await Promise.allSettled([
            getHistory(queryThreadId),
            getConversationTitle(queryThreadId),
          ])

          if (historyResult.status === "fulfilled") {
            setMessages(
              historyResult.value.messages.map((message) => toLocalMessage(message)),
            )
            // Auto-select the latest request_id (from last AI message)
            const lastAiMessage = historyResult.value.messages
              .filter((m: ChatMessage) => m.type === "ai")
              .pop()
            if (lastAiMessage?.request_id) {
              setSelectedRequestId(lastAiMessage.request_id)
            } else {
              setSelectedRequestId(null)
            }
          } else {
            setMessages([])
            setSelectedRequestId(null)
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
          // New conversation: delay thread_id creation until first message is sent
          setThreadId("")
          setConversationTitleState(defaultConversationTitle)
          setDraftTitle(defaultConversationTitle)
          setMessages([])
          writeUrl(null)
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
          // Reset needsReinit flag after bootstrap completes
          setNeedsReinit(false)
        }
      }
    }

    void bootstrap()

    return () => {
      cancelled = true
      abortControllerRef.current?.abort()
    }
  }, [writeUrl, needsReinit, isLoggedIn, defaultConversationTitle])

  // Handle user login from home page
  const handleUserLogin = useCallback((user: UserInfo) => {
    setUserId(user.id)
    setCurrentUserId(user.id)
    // Trigger re-initialization after login to ensure proper data loading
    setNeedsReinit(true)
  }, [setUserId])

  // If still loading auth status, show nothing (or loading indicator)
  if (isAuthLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-muted-foreground">Loading...</div>
      </div>
    )
  }

  // If no user is logged in (neither mock nor WeChat), show the home page
  if (!isLoggedIn) {
    return (
      <>
        <HomePage onSelectUser={handleUserLogin} />
        <Toaster />
      </>
    )
  }

  return (
    <>
      <SidebarProvider defaultOpen className="h-screen min-h-0 overflow-hidden">
        <ChatSidebar
          threadId={threadId}
          conversations={conversations}
          onCreateConversation={resetToNewConversation}
          disableCreateConversation={isInitializing || isLoadingConversation}
          onOpenConversation={(conversation) => {
            void openConversation(
              conversation.thread_id,
              conversations,
            )
          }}
          onRenameConversation={startRenameConversation}
          onDeleteConversation={setDeleteTarget}
          hasMore={hasMoreConversations}
          isLoadingMore={isLoadingMoreConversations}
          onLoadMore={handleLoadMoreConversations}
          onSwitchUser={handleSwitchUser}
          currentUser={currentUser}
        />

        <SidebarInset className="min-h-0 overflow-hidden bg-background flex-1">
          <ChatMainPanel
            appError={appError}
            isStreaming={isStreaming}
            isInitializing={isInitializing}
            isLoadingConversation={isLoadingConversation}
            isProcessing={isProcessing}
            isAgentThinking={isAgentThinking}
            calledTools={calledTools}
            thinkingContent={thinkingContent}
            messages={messages}
            onSendMessage={handleSendMessage}
            onStopStreaming={stopStreaming}
            onJumpToMessage={jumpToMessage}
            onToggleSidebarProcess={() => setShowSidebarProcess(prev => !prev)}
            onSelectRequestId={(requestId: string | null) => {
              setSelectedRequestId(requestId)
              // Ensure sidebar is visible
              if (!showSidebarProcess) {
                setShowSidebarProcess(true)
              }
            }}
            models={models}
            selectedModel={effectiveSelectedModel}
            onSelectModel={setSelectedModel}
            onOpenModelConfig={() => setShowProviderConfig(true)}
            hasAvailableModels={hasAvailableModels}
            selectedRequestId={selectedRequestId}
          />
        </SidebarInset>

        {/* Right Panel - same width as left sidebar (16rem) */}
        <aside className="hidden md:flex flex-col gap-2 border-l border-border bg-background p-2 w-64 min-w-64">
          {/* Top Section: Configuration */}
          <div className="space-y-2">
            {/* Four buttons horizontally */}
            <div className="flex gap-1 w-full">
              <Button
                type="button"
                size="icon"
                variant="outline"
                className="size-8 flex-1 hover:bg-primary/10 hover:border-primary/40 hover:text-primary dark:hover:bg-primary/20 dark:hover:border-primary/60 dark:hover:text-primary"
                disabled={messages.length === 0}
                onClick={() => {
                  navigator.clipboard.writeText(window.location.href)
                  setShowShareDialog(true)
                }}
                aria-label={t("share.button")}
                title={t("share.button")}
              >
                <Share2 className="size-4" />
              </Button>
              <Button
                type="button"
                size="icon"
                variant="outline"
                className="cursor-pointer size-8 flex-1 hover:bg-primary/10 hover:border-primary/40 hover:text-primary dark:hover:bg-primary/20 dark:hover:border-primary/60 dark:hover:text-primary"
                onClick={toggleTheme}
                aria-label={t("theme.switch")}
                title={t("theme.switch")}
              >
                {theme === "light" ? (
                  <Sun className="size-4" />
                ) : (
                  <Moon className="size-4" />
                )}
              </Button>
              <Button
                type="button"
                size="icon"
                variant="outline"
                className="cursor-pointer size-8 flex-1 hover:bg-primary/10 hover:border-primary/40 hover:text-primary dark:hover:bg-primary/20 dark:hover:border-primary/60 dark:hover:text-primary"
                onClick={toggleLocale}
                aria-label={t("language.switch")}
                title={t("language.switch")}
              >
                <Languages className="size-4" />
              </Button>
              <Button
                type="button"
                size="icon"
                variant="outline"
                className="cursor-pointer size-8 flex-1 hover:bg-primary/10 hover:border-primary/40 hover:text-primary dark:hover:bg-primary/20 dark:hover:border-primary/60 dark:hover:text-primary"
                onClick={() => setShowProviderConfig(true)}
                aria-label={t("provider.configure")}
                title={t("provider.configure")}
              >
                <Settings className="size-4" />
              </Button>
            </div>

          </div>

          {/* Middle Section: Turn DAG Sidebar */}
          <div className="flex-1 min-h-0 overflow-hidden">
            {!isInitializing && threadId && messages.length > 0 && (
              <TurnDAGSidebar
                threadId={threadId || null}
                isStreaming={isStreaming}
                requestId={selectedRequestId}
              />
            )}
          </div>

          {/* Bottom Section: Token Stats - only show in chat mode */}
          {!isInitializing && messages.length > 0 && (
            <TokenStatsPanel
              currentConversation={conversations.find(c => c.thread_id === threadId) ?? null}
            />
          )}
        </aside>
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

      <ShareDialog
        open={showShareDialog}
        onOpenChange={setShowShareDialog}
      />

      {/* Provider Config Dialog */}
      <ProviderConfigDialog
        open={showProviderConfig}
        onOpenChange={(open) => {
          setShowProviderConfig(open)
          if (!open) {
            void refreshModels()
          }
        }}
      />

      {/* No Model Dialog */}
      <AlertDialog open={showNoModelDialog} onOpenChange={setShowNoModelDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("model.noModelDialogTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("model.noModelDialogDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("model.noModelDialogCancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setShowNoModelDialog(false)
                setShowProviderConfig(true)
              }}
            >
              {t("model.noModelDialogConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Toast notifications */}
      <Toaster />
    </>
  )
}

export default App
