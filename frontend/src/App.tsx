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
  generateTitle,
  getConversationTitle,
  getHistory,
  listAgents,
  listConversations,
  loadMoreConversations,
  setConversationTitle,
  streamChat,
} from "@/lib/api"
import type {
  AgentInDB,
  AgentProcessSession,
  AgentProcessStep,
  ChatMessage,
  ConversationInDB,
  LocalChatMessage,
  MessageStep,
  StreamEvent,
  ToolCallEvent,
  ToolCallInfo,
} from "@/types"
import { useThinkingMode } from "@/hooks/use-thinking-mode"
import { useTheme } from "@/hooks/use-theme"
import { useModels } from "@/hooks/use-models"
import {
  AgentProcessPanel,
  ChatMainPanel,
  ChatSidebar,
  ConversationRenameDialog,
  DeleteConversationDialog,
  ShareDialog,
  TokenStatsPanel,
} from "@/features/chat/components"
import { AgentSidebar } from "@/components/agent"
import { ProviderConfigDialog } from "@/features/chat/components/provider-config-dialog"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Button } from "@/components/ui/button"
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
import { Toaster } from "@/components/ui/toaster"

function App() {
  const { t, toggleLocale } = useI18n()
  const { theme, toggleTheme } = useTheme()
  const defaultConversationTitle = t("conversation.defaultTitle")

  const [agents, setAgents] = useState<AgentInDB[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState("")

  const [conversations, setConversations] = useState<ConversationInDB[]>([])
  const [threadId, setThreadId] = useState("")
  // Pagination state for conversations
  const [conversationsOffset, setConversationsOffset] = useState(0)
  const [hasMoreConversations, setHasMoreConversations] = useState(true)
  const [isLoadingMoreConversations, setIsLoadingMoreConversations] = useState(false)

  // Thinking mode state - persisted per conversation in localStorage
  const {
    thinkingMode
  } = useThinkingMode(threadId)

  // Model selection state - persisted per conversation in localStorage
  const {
    models,
    setSelectedModel,
    getEffectiveModel,
    refreshModels,
  } = useModels(threadId)

  // Get the effective model ID (selected or default)
  const effectiveSelectedModel = getEffectiveModel()

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

  // Agent process session for real-time sidebar display
  const [processSession, setProcessSession] = useState<AgentProcessSession | null>(null)
  // Message sequence from backend - all messages as steps for sidebar
  const [messageSequence, setMessageSequence] = useState<MessageStep[]>([])
  // Toggle for showing/hiding the sidebar process panel
  const [showSidebarProcess, setShowSidebarProcess] = useState(true)


  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)



  const [renameTarget, setRenameTarget] = useState<ConversationInDB | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ConversationInDB | null>(null)
  const [showShareDialog, setShowShareDialog] = useState(false)
  const [showProviderConfig, setShowProviderConfig] = useState(false)
  const [showNoModelDialog, setShowNoModelDialog] = useState(false)

  const abortControllerRef = useRef<AbortController | null>(null)
  const streamingPlaceholderIdRef = useRef<string | null>(null)
  const isProcessingRef = useRef(false)
  const thinkingModeRef = useRef(thinkingMode)
  const effectiveModelRef = useRef<string | null>(null)
  const processSessionRef = useRef<AgentProcessSession | null>(null)
  // Store pending tool calls (id -> ToolCallEvent) for creating steps when tool_result arrives
  const pendingToolCallsRef = useRef<Map<string, ToolCallEvent>>(new Map())
  // Direct ref for process steps to avoid race condition with React state sync
  const processStepsRef = useRef<AgentProcessStep[]>([])

  // Keep thinkingModeRef in sync with thinkingMode state
  useEffect(() => {
    thinkingModeRef.current = thinkingMode
  }, [thinkingMode])

  // Keep effectiveModelRef in sync with effectiveSelectedModel state
  useEffect(() => {
    effectiveModelRef.current = effectiveSelectedModel
  }, [effectiveSelectedModel])

  // Keep processSessionRef in sync with processSession state
  useEffect(() => {
    processSessionRef.current = processSession
  }, [processSession])

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
        setConversations((prev) =>
          sortConversationsByUpdatedAt([...prev, ...moreConversations])
        )
        setConversationsOffset((prev) => prev + moreConversations.length)
        setHasMoreConversations(conversationsOffset + moreConversations.length < total)
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
      setThreadId(targetThreadId)
      writeThreadIdToUrl(targetThreadId)
      setRenameTarget(null)
      setIsLoadingConversation(true)
      setAppError(null)
      // Clear process display when switching conversations
      setProcessSession(null)

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
          // Set message sequence for sidebar
          const sequence = historyResult.value.message_sequence || []
          setMessageSequence(sequence)

          // Auto-select the latest session that has steps
          if (sequence && sequence.length > 0) {
            // Group steps by session_id
            const stepsBySession = new Map<string, MessageStep[]>()
            sequence.forEach((step) => {
              const sid = step.session_id
              if (!stepsBySession.has(sid)) {
                stepsBySession.set(sid, [])
              }
              stepsBySession.get(sid)!.push(step)
            })

            // Find sessions that have steps (tool calls or thinking)
            const sessionsWithSteps: string[] = []
            stepsBySession.forEach((steps, sid) => {
              const hasToolSteps = steps.some(s => s.message_type === "tool")
              const hasThinking = steps.some(s => s.message_type === "ai" && s.thinking && s.thinking.trim().length > 0)
              if (hasToolSteps || hasThinking) {
                sessionsWithSteps.push(sid)
              }
            })

            // Select the latest session with steps
            if (sessionsWithSteps.length > 0) {
              setSelectedSessionId(sessionsWithSteps[sessionsWithSteps.length - 1])
            } else {
              setSelectedSessionId(null)
            }
          } else {
            setSelectedSessionId(null)
          }
        } else {
          setMessages([])
          setMessageSequence([])
          setSelectedSessionId(null)
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
    setMessageSequence([]) // Clear message sequence for new conversation
    setConversationTitleState(defaultConversationTitle)
    setDraftTitle(defaultConversationTitle)
    setRenameTarget(null)
    setSelectedAgentId(agents[0]?.agent_id ?? "chatbot") // Use first agent as default
    setAppError(null)
    // Clear process display when creating new conversation
    setProcessSession(null)
  }, [writeThreadIdToUrl, defaultConversationTitle, agents])

  const pickAgentForCurrentConversation = useCallback((agentId: string) => {
    setSelectedAgentId(agentId)
    setAppError(null)
  }, [])

  // Ensure chatbot is selected by default when no agent is selected
  useEffect(() => {
    if (!selectedAgentId && agents.length > 0) {
      // Find chatbot agent, or use first agent as fallback
      const chatbotAgent = agents.find(a => a.agent_id === 'chatbot')
      setSelectedAgentId(chatbotAgent?.agent_id ?? agents[0]?.agent_id ?? "")
    }
  }, [selectedAgentId, agents])

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

            return previous.map((item, index) => {
              if (index === previous.length - 1) {
                return {
                  ...item,
                  content: mergedContent,
                  tool_calls: mergedToolCalls,
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
            user_message: userInput,
            ai_response: aiResponse,
          })

          const generatedTitle = sanitizeTitle(result.title)

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
        !threadId ||
        !selectedAgentId ||
        isStreaming
      ) {
        return
      }

      setAppError(null)
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

      const targetThreadId = threadId
      const currentTitle = conversationTitle

      try {
        await ensureConversationExists(targetThreadId, currentTitle)

        // Write thread_id to URL for sharing (especially important for new conversations)
        writeThreadIdToUrl(targetThreadId)

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

        // Initialize process session for real-time sidebar display
        // Start with human message as step 0 (matching backend)
        const humanStep: AgentProcessStep = {
          id: `human-${Date.now()}`,
          type: "human",
          content: trimmed,
          timestamp: Date.now(),
          status: "done",
        }

        setProcessSession({
          threadId: targetThreadId,
          agentId: selectedAgentId,
          steps: [humanStep],
          isActive: true,
          startTime: Date.now(),
        })
        // Reset process steps ref for direct access (avoids race condition)
        // Include human message as first step (step 0)
        processStepsRef.current = [humanStep]

        // Use ref to get the latest thinkingMode and model value to avoid stale closure
        const currentThinkingMode = thinkingModeRef.current
        const currentModel = effectiveModelRef.current

        await streamChat(
          {
            content: trimmed,
            agent_id: selectedAgentId,
            thread_id: targetThreadId,
            model_name: currentModel,
            thinking_mode: currentThinkingMode,
            custom_data: quotedMessageId ? {
              quoted_message_id: quotedMessageId,
              user_content: userContent,
            } : undefined,
          },
          (event: StreamEvent) => {
            // Received any content, stop showing "processing..."
            if (isProcessingRef.current) {
              setIsProcessing(false)
              isProcessingRef.current = false
            }

            if (event.type === "llm") {
              // Thinking/reasoning content from models like DeepSeek-R1, Qwen3
              setIsAgentThinking(true)
              setActiveToolCall(null)
              // Accumulate thinking content
              setThinkingContent((prev) => prev + event.content)

              // Update process steps ref directly (avoids race condition)
              // Use id to identify the same step and append content
              const currentSteps = processStepsRef.current
              const existingStepIndex = currentSteps.findIndex(s => s.id === event.id)

              if (existingStepIndex >= 0) {
                // Append to existing step (streaming)
                const existingStep = currentSteps[existingStepIndex]
                currentSteps[existingStepIndex] = {
                  ...existingStep,
                  content: (existingStep.content as string) + event.content,
                }
              } else {
                // Create new thinking step (new LLM call)
                const newStep: AgentProcessStep = {
                  id: event.id,
                  type: "thinking",
                  content: event.content,
                  timestamp: Date.now(),
                  status: "running",
                }
                processStepsRef.current = [...currentSteps, newStep]
              }

              // Update process session for UI display
              setProcessSession((prev) => {
                if (!prev) return null
                return { ...prev, steps: processStepsRef.current }
              })
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

            if (event.type === "tool") {
              // Agent is calling a tool, show thinking state
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

              // Mark thinking as done
              processStepsRef.current = processStepsRef.current.map((step) => {
                if (step.type === "thinking" && step.status === "running") {
                  return { ...step, status: "done" as const }
                }
                return step
              })

              // Create tool_call step immediately (tool is being executed)
              const newStep: AgentProcessStep = {
                id: event.id,
                type: "tool_call",
                content: toolCallEvent,
                timestamp: Date.now(),
                status: "running",
              }
              processStepsRef.current = [...processStepsRef.current, newStep]

              // Store pending tool call for result matching
              pendingToolCallsRef.current.set(event.content.tool_id, toolCallEvent)

              // Update process session for UI display
              setProcessSession((prev) => {
                if (!prev) return null
                return { ...prev, steps: processStepsRef.current }
              })

              // Reset thinking content for the next LLM call
              setThinkingContent("")
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

              // Find and update the existing tool step with the result
              // The tool step was created when tool event was received
              processStepsRef.current = processStepsRef.current.map((step) => {
                // Match by tool_id stored in the content
                if (step.type === "tool_call" && step.status === "running") {
                  const toolContent = step.content as ToolCallEvent
                  if (toolContent.id === event.content.id) {
                    return { ...step, status: "done" as const, result: event.content.output }
                  }
                }
                return step
              })

              // Clean up pending tool call
              pendingToolCallsRef.current.delete(event.content.id)

              // Update process session for UI display
              setProcessSession((prev) => {
                if (!prev) return null
                return { ...prev, steps: processStepsRef.current }
              })
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

        // Add AI response step to process steps before saving
        // Get the final AI message content
        let finalAiContent = ""
        let finalThinkingContent = ""
        setMessages((previous) => {
          for (let i = previous.length - 1; i >= 0; i--) {
            if (previous[i].type === "ai" && previous[i].content) {
              finalAiContent = previous[i].content
              finalThinkingContent = previous[i].custom_data?.thinking as string || ""
              break
            }
          }
          return previous
        })

        // Add AI response step if we have content
        if (finalAiContent) {
          const aiResponseStep: AgentProcessStep = {
            id: `ai-response-${Date.now()}`,
            type: "ai_response",
            content: finalAiContent,
            timestamp: Date.now(),
            status: "done",
            thinking: finalThinkingContent || undefined,
          }
          processStepsRef.current = [...processStepsRef.current, aiResponseStep]

          // Update process session for UI display
          setProcessSession((prev) => {
            if (!prev) return null
            return { ...prev, steps: processStepsRef.current }
          })
        }

        // Ensure all streaming placeholders are marked as complete
        // Also save process steps to the message's custom_data for history
        // Use processStepsRef directly to avoid race condition with React state sync
        setMessages((previous) => {
          const updated = previous.map((message) => {
            if (!message.is_streaming) {
              return message
            }
            // Get the final process steps from processStepsRef (avoids race condition)
            const finalSteps = processStepsRef.current

            // Convert steps to historical format for persistence
            const processSteps = finalSteps.map((step, index) => ({
              id: step.id,
              type: step.type,
              content: step.type === "thinking" || step.type === "human" || step.type === "ai_response"
                ? step.content as string
                : (step.content as ToolCallEvent).name,
              args: step.type === "tool_call" ? (step.content as ToolCallEvent).args : undefined,
              result: step.result,
              thinking: step.thinking,
              order: index,
            }))

            return {
              ...message,
              is_streaming: false,
              custom_data: {
                ...message.custom_data,
                process_steps: processSteps,
              },
            }
          })
          return updated
        })

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
        // Mark process session as inactive
        setProcessSession((prev) => {
          if (!prev) return null
          return {
            ...prev,
            isActive: false,
            endTime: Date.now(),
          }
        })

        // Fetch updated message sequence from backend for sidebar persistence
        // This ensures the sidebar shows correct data after streaming ends
        try {
          const historyResult = await getHistory(selectedAgentId, targetThreadId)
          if (historyResult.message_sequence) {
            setMessageSequence(historyResult.message_sequence)

            // Auto-select the latest session that has steps
            const sequence = historyResult.message_sequence
            if (sequence && sequence.length > 0) {
              // Group steps by session_id
              const stepsBySession = new Map<string, MessageStep[]>()
              sequence.forEach((step) => {
                const sid = step.session_id
                if (!stepsBySession.has(sid)) {
                  stepsBySession.set(sid, [])
                }
                stepsBySession.get(sid)!.push(step)
              })

              // Find sessions that have steps (tool calls or thinking)
              const sessionsWithSteps: string[] = []
              stepsBySession.forEach((steps, sid) => {
                const hasToolSteps = steps.some(s => s.message_type === "tool")
                const hasThinking = steps.some(s => s.message_type === "ai" && s.thinking && s.thinking.trim().length > 0)
                if (hasToolSteps || hasThinking) {
                  sessionsWithSteps.push(sid)
                }
              })

              // Select the latest session with steps
              if (sessionsWithSteps.length > 0) {
                setSelectedSessionId(sessionsWithSteps[sessionsWithSteps.length - 1])
              }
            }
          }
        } catch {
          // Ignore errors when fetching message sequence
        }
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
      selectedAgentId,
      t,
      threadId,
      writeThreadIdToUrl,
    ],
  )

  const handleEditMessage = useCallback(
    async (newContent: string, messageIndex: number) => {
      if (!threadId || !selectedAgentId || isStreaming) {
        return
      }

      // Validate the message index
      if (messageIndex < 0 || messageIndex >= messages.length) {
        return
      }

      // Ensure the message at the index is a user message
      const messageToEdit = messages[messageIndex]
      if (messageToEdit.type !== "human") {
        return
      }

      // Keep messages before the edited message
      const previousMessages = messages.slice(0, messageIndex)

      // Create placeholder ID before any state updates
      const placeholderId = crypto.randomUUID()
      streamingPlaceholderIdRef.current = placeholderId

      // Keep messages before the edited message, then add the edited user message
      // This ensures history is visible while editing
      const editedUserMessage = toLocalMessage(
        { type: "human", content: newContent },
        { customData: messageToEdit.custom_data }
      )

      // Create AI placeholder in the same state update to avoid race condition
      const aiPlaceholder = toLocalMessage(
        { type: "ai", content: "" },
        { localId: placeholderId, isStreaming: true }
      )

      // Single state update with all messages
      setMessages([...previousMessages, editedUserMessage, aiPlaceholder])

      setAppError(null)
      setIsStreaming(true)

      const controller = new AbortController()
      abortControllerRef.current = controller

      // Reset state
      setIsProcessing(true)
      isProcessingRef.current = true
      setIsAgentThinking(false)
      setCalledTools([])
      setThinkingContent("")

      const currentThinkingMode = thinkingModeRef.current
      const currentModel = effectiveModelRef.current

      try {
        // Stream with the new content
        await streamChat(
          {
            content: newContent,
            agent_id: selectedAgentId,
            thread_id: threadId,
            model_name: currentModel,
            thinking_mode: currentThinkingMode,
          },
          (event: StreamEvent) => {
            if (isProcessingRef.current) {
              setIsProcessing(false)
              isProcessingRef.current = false
            }

            if (event.type === "llm") {
              setIsAgentThinking(true)
              setActiveToolCall(null)
              setThinkingContent((prev) => prev + event.content)
              return
            }

            if (event.type === "token") {
              setIsAgentThinking(false)
              setActiveToolCall(null)
              addStreamToken(event.content)
              return
            }

            if (event.type === "message") {
              const message = event.content
              if (message.type === "ai") {
                const hasContent = message.content && message.content.trim().length > 0
                const hasToolCalls = message.tool_calls && message.tool_calls.length > 0
                if (hasContent && !hasToolCalls) {
                  setIsAgentThinking(false)
                  setActiveToolCall(null)
                }
              }
              addMessageFromStream(message)
              return
            }

            if (event.type === "tool") {
              setIsAgentThinking(true)
              const toolCallEvent: ToolCallEvent = {
                name: event.content.name,
                id: event.content.tool_id,
                args: event.content.args,
              }
              setActiveToolCall(toolCallEvent)
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
              // Token usage event - log for debugging
              console.log(
                `[${event.content.node}] Token usage:`,
                `input=${event.content.usage.input_tokens ?? 'N/A'},`,
                `output=${event.content.usage.output_tokens ?? 'N/A'},`,
                `total=${event.content.usage.total_tokens ?? 'N/A'}`
              )
              return
            }

            // error event
            if (event.type === "error") {
              setAppError(event.content)
            }
          },
          controller.signal,
        )

        // Mark streaming complete
        setMessages((previous) => {
          const updated = previous.map((message) =>
            message.is_streaming
              ? { ...message, is_streaming: false }
              : message,
          )
          return updated
        })

        await refreshConversations()
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          const details = getErrorMessage(error, t("error.unexpected"))
          setAppError(t("error.generateResponse", { details }))
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
      isStreaming,
      messages,
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
    let cancelled = false

    async function bootstrap() {
      setIsInitializing(true)
      setAppError(null)

      try {
        const [agentResult, conversationResult] = await Promise.all([
          listAgents(),
          listConversations(10, 0),
        ])

        if (cancelled) {
          return
        }

        const agentList = agentResult.agents
        setAgents(agentList)
        const defaultAgentId = agentList[0]?.agent_id ?? "chatbot"

        const conversationList = conversationResult.conversations
        const sorted = sortConversationsByUpdatedAt(conversationList)
        setConversations(sorted)

        const queryThreadId = readThreadIdFromUrl()
        const queryAgentId = readAgentIdFromUrl()

        // If URL has agent_id parameter, use that agent directly
        if (queryAgentId) {
          const validAgentId = agentList.some(
            (agent) => agent.agent_id === queryAgentId
          )
            ? queryAgentId
            : ""
          setSelectedAgentId(validAgentId)
        }
        // If no agent_id in URL, use default agent

        if (queryThreadId) {
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
            // Set message sequence for sidebar
            setMessageSequence(historyResult.value.message_sequence || [])
          } else {
            setMessages([])
            setMessageSequence([])
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
          // Use default agent for new conversation
          setSelectedAgentId(defaultAgentId)
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
              agents,
            )
          }}
          onRenameConversation={startRenameConversation}
          onDeleteConversation={setDeleteTarget}
          hasMore={hasMoreConversations}
          isLoadingMore={isLoadingMoreConversations}
          onLoadMore={handleLoadMoreConversations}
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
            agents={agents}
            selectedAgentId={selectedAgentId}
            processSession={processSession}
            messageSequence={messageSequence}
            onSendMessage={handleSendMessage}
            onStopStreaming={stopStreaming}
            onSelectAgent={pickAgentForCurrentConversation}
            onEditMessage={handleEditMessage}
            onJumpToMessage={jumpToMessage}
            onToggleSidebarProcess={() => setShowSidebarProcess(prev => !prev)}
            aiMessageSessionIds={useMemo(() => {
              // Build a map of message index to session_id
              // Each AI message should have a corresponding session_id from messageSequence
              if (!messageSequence || messageSequence.length === 0) {
                return []
              }

              // Get all AI steps from messageSequence, grouped by session_id
              const sessionIds: (string | null)[] = []

              // For each message in messages array, determine its session_id
              // AI messages have session_id from messageSequence
              // User messages have null
              messages.forEach((msg, index) => {
                if (msg.type === "ai") {
                  // Find the corresponding session_id from messageSequence
                  // The AI steps in messageSequence are in order
                  const aiSteps = messageSequence.filter(s => s.message_type === "ai")
                  const aiIndex = messages.slice(0, index + 1).filter(m => m.type === "ai").length - 1
                  sessionIds.push(aiSteps[aiIndex]?.session_id || null)
                } else {
                  sessionIds.push(null)
                }
              })

              return sessionIds
            }, [messageSequence, messages])}
            aiMessageHasSteps={useMemo(() => {
              // For each message, determine if it has steps based on its session_id
              const hasSteps: boolean[] = []

              // Pre-compute which sessions have steps
              const sessionsWithSteps = new Set<string>()
              if (messageSequence && messageSequence.length > 0) {
                messageSequence.forEach(step => {
                  if (step.message_type === "tool" || (step.message_type === "ai" && step.thinking?.trim())) {
                    sessionsWithSteps.add(step.session_id)
                  }
                })
              }

              // Get session IDs for each message (same logic as aiMessageSessionIds)
              const getSessionId = (msgIndex: number): string | null => {
                const msg = messages[msgIndex]
                if (msg?.type !== "ai") return null
                const aiSteps = messageSequence?.filter(s => s.message_type === "ai") || []
                const aiIndex = messages.slice(0, msgIndex + 1).filter(m => m.type === "ai").length - 1
                return aiSteps[aiIndex]?.session_id || null
              }

              messages.forEach((msg, index) => {
                if (msg.type !== "ai") {
                  hasSteps.push(false)
                  return
                }

                // Check 1: Does message have process_steps from streaming?
                const processSteps = msg.custom_data?.process_steps
                if (Array.isArray(processSteps) && processSteps.length > 0) {
                  hasSteps.push(true)
                  return
                }

                // Check 2: Does message have tool calls?
                if (msg.tool_calls && msg.tool_calls.length > 0) {
                  hasSteps.push(true)
                  return
                }

                // Check 3: Does message have thinking content?
                if (msg.custom_data?.thinking || msg.response_metadata?.thinking || msg.reasoning_content) {
                  hasSteps.push(true)
                  return
                }

                // Check 4: Does the message's session have steps?
                const sessionId = getSessionId(index)
                if (sessionId && sessionsWithSteps.has(sessionId)) {
                  hasSteps.push(true)
                  return
                }

                hasSteps.push(false)
              })

              return hasSteps
            }, [messageSequence, messages])}


            onSelectSession={(sessionId: string) => {
              setSelectedSessionId(sessionId)
              // Ensure sidebar is visible when selecting a session
              if (!showSidebarProcess) {
                setShowSidebarProcess(true)
              }
            }}
            models={models}
            selectedModel={effectiveSelectedModel}
            onSelectModel={setSelectedModel}
            onSelectAgentId={pickAgentForCurrentConversation}
            onOpenModelConfig={() => setShowProviderConfig(true)}
            hasAvailableModels={hasAvailableModels}
            selectedSessionId={selectedSessionId}
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

          {/* Middle Section: Agent Process Panel (chat mode) or Agent Sidebar (home mode) */}
          <div className="flex-1 min-h-0 overflow-hidden">
            {!isInitializing && (
              messages.length === 0 ? (
                // Home mode: Show available agents in sidebar
                <AgentSidebar
                  agents={agents}
                  selectedAgentId={selectedAgentId}
                  onSelectAgent={pickAgentForCurrentConversation}
                />
              ) : (
                // Chat mode: Show agent process panel
                showSidebarProcess && (messageSequence.length > 0 || (processSession && processSession.steps && processSession.steps.length > 0)) && (
                  <AgentProcessPanel
                    session={processSession}
                    messageSequence={messageSequence}
                    isStreaming={isStreaming}
                    selectedSessionId={selectedSessionId}
                  />
                )
              )
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
