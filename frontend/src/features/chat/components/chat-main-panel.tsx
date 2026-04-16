import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ArrowDown, XIcon } from "lucide-react"

import type { AgentInDB, LocalChatMessage, ToolCallInfo, AgentProcessSession, MessageStep } from "@/types"
import { ThinkingModeToggle } from "@/features/chat/components/thinking-mode-toggle"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai/prompt-input"
import { ChatMessageItem } from "@/features/chat/components/chat-message-item"
import { Loader } from "~/components/ai/loader"
import { AgentGrid } from "@/components/agent"
import { useI18n } from "@/i18n"

type ChatMainPanelProps = {
  appError: string | null
  isStreaming: boolean
  isInitializing: boolean
  isLoadingConversation: boolean
  isAwaitingAgentSelection: boolean
  isProcessing: boolean // Processing, no content received yet
  isAgentThinking: boolean
  calledTools: ToolCallInfo[]
  thinkingContent: string // Accumulated thinking content
  messages: LocalChatMessage[]
  agents: AgentInDB[]
  selectedAgentId: string
  processSession?: AgentProcessSession | null // Process session for inline display during streaming
  messageSequence?: MessageStep[] // Message sequence for historical display
  onSendMessage: (rawInput: string, quotedMessageId?: string, userContent?: string) => Promise<void>
  onStopStreaming: () => void
  onSelectAgent: (agentId: string) => void
  thinkingMode: boolean
  onToggleThinkingMode: () => void
  modelSupportsThinking: boolean // Whether current model supports thinking mode
  onEditMessage?: (newContent: string, messageIndex: number) => Promise<void>
  onJumpToMessage?: (localId: string) => void // Jump to message callback
  onToggleSidebarProcess?: () => void // Toggle sidebar process panel visibility
}

const SCROLL_BOTTOM_HIDE_THRESHOLD = 24
const SCROLL_BUTTON_SHOW_OFFSET = 180
const SCROLLBAR_FADE_OUT_DELAY = 420
const STREAM_SCROLL_EASING = 0.2
const STREAM_SCROLL_MIN_STEP = 1
const USER_SCROLL_INTERRUPT_DELTA = -2

export function ChatMainPanel({
  appError,
  isStreaming,
  isInitializing,
  isLoadingConversation,
  isAwaitingAgentSelection,
  isProcessing,
  isAgentThinking,
  calledTools,
  thinkingContent,
  messages,
  agents,
  selectedAgentId,
  processSession,
  messageSequence,
  onSendMessage,
  onStopStreaming,
  onSelectAgent,
  thinkingMode,
  onToggleThinkingMode,
  modelSupportsThinking,
  onEditMessage,
  onJumpToMessage,
  onToggleSidebarProcess,
}: ChatMainPanelProps) {
  const { t } = useI18n()
  const [inputValue, setInputValue] = useState("")

  // Quote state - show quoted content above input
  const [quotedContent, setQuotedContent] = useState<string | null>(null)
  const [quotedMessageId, setQuotedMessageId] = useState<string | null>(null)

  const endOfMessagesRef = useRef<HTMLDivElement | null>(null)
  const conversationRef = useRef<HTMLDivElement | null>(null)
  const scrollbarHideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const streamFollowRafRef = useRef<number | null>(null)
  const autoScrollEnabledRef = useRef(true)
  const isStreamingRef = useRef(isStreaming)
  const lastKnownScrollTopRef = useRef(0)
  const [showScrollButton, setShowScrollButton] = useState(false)
  const [isMessagesScrolling, setIsMessagesScrolling] = useState(false)

  const suggestions = useMemo(
    () => [
      t("chat.suggestion.1"),
      t("chat.suggestion.2"),
      t("chat.suggestion.3"),
      t("chat.suggestion.4"),
    ],
    [t],
  )

  const status: "streaming" | "submitted" | "ready" = useMemo(() => {
    if (isStreaming) {
      return "streaming"
    }
    if (isInitializing || isLoadingConversation) {
      return "submitted"
    }
    return "ready"
  }, [isInitializing, isLoadingConversation, isStreaming])

  const isComposerDisabled =
    isInitializing || isLoadingConversation || isAwaitingAgentSelection

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const element = conversationRef.current
    if (!element) {
      return
    }
    element.scrollTo({ top: element.scrollHeight, behavior })
  }, [])

  const stopStreamFollow = useCallback(() => {
    if (streamFollowRafRef.current !== null) {
      window.cancelAnimationFrame(streamFollowRafRef.current)
      streamFollowRafRef.current = null
    }
  }, [])

  const startStreamFollow = useCallback(() => {
    if (streamFollowRafRef.current !== null) {
      return
    }

    const step = () => {
      const element = conversationRef.current
      if (!element || !isStreamingRef.current || !autoScrollEnabledRef.current) {
        streamFollowRafRef.current = null
        return
      }

      const targetTop = element.scrollHeight - element.clientHeight
      const distance = targetTop - element.scrollTop

      if (distance <= 0.5) {
        element.scrollTop = targetTop
      } else {
        element.scrollTop += Math.max(STREAM_SCROLL_MIN_STEP, distance * STREAM_SCROLL_EASING)
      }

      streamFollowRafRef.current = window.requestAnimationFrame(step)
    }

    streamFollowRafRef.current = window.requestAnimationFrame(step)
  }, [])

  useEffect(() => {
    isStreamingRef.current = isStreaming
    if (!isStreaming) {
      stopStreamFollow()
    }
  }, [isStreaming, stopStreamFollow])

  useEffect(() => {
    if (isAwaitingAgentSelection || isLoadingConversation || !autoScrollEnabledRef.current) {
      return
    }

    if (isStreaming) {
      startStreamFollow()
      return
    }

    scrollToBottom("auto")
  }, [
    isAwaitingAgentSelection,
    isLoadingConversation,
    isStreaming,
    messages,
    scrollToBottom,
    startStreamFollow,
  ])

  useEffect(() => {
    return () => {
      if (scrollbarHideTimerRef.current) {
        clearTimeout(scrollbarHideTimerRef.current)
      }
      stopStreamFollow()
    }
  }, [stopStreamFollow])

  const updateScrollButtonState = useCallback(() => {
    const element = conversationRef.current
    if (!element) {
      return
    }

    setIsMessagesScrolling(true)
    if (scrollbarHideTimerRef.current) {
      clearTimeout(scrollbarHideTimerRef.current)
    }
    scrollbarHideTimerRef.current = setTimeout(() => {
      setIsMessagesScrolling(false)
    }, SCROLLBAR_FADE_OUT_DELAY)

    const distanceFromBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight
    const isAtBottom = distanceFromBottom <= SCROLL_BOTTOM_HIDE_THRESHOLD
    const scrollDelta = element.scrollTop - lastKnownScrollTopRef.current
    lastKnownScrollTopRef.current = element.scrollTop

    if (isAtBottom) {
      autoScrollEnabledRef.current = true
      if (isStreamingRef.current) {
        startStreamFollow()
      }
    } else if (isStreamingRef.current && scrollDelta < USER_SCROLL_INTERRUPT_DELTA) {
      autoScrollEnabledRef.current = false
      stopStreamFollow()
    }

    setShowScrollButton(!isAtBottom && distanceFromBottom > SCROLL_BUTTON_SHOW_OFFSET)
  }, [startStreamFollow, stopStreamFollow])

  const submitMessage = useCallback((rawInput: string) => {
    const trimmed = rawInput.trim()
    if (!trimmed || isStreaming || isComposerDisabled) {
      return
    }

    // If there's quoted content, format the message and pass quotedMessageId
    const finalContent = quotedContent
      ? `> ${quotedContent}\n\n${trimmed}`
      : trimmed

    setInputValue("")
    const currentQuotedMessageId = quotedMessageId
    setQuotedContent(null)
    setQuotedMessageId(null)

    // Pass quotedMessageId and userContent for display purposes
    void onSendMessage(finalContent, currentQuotedMessageId || undefined, trimmed)
  }, [isComposerDisabled, isStreaming, onSendMessage, quotedContent, quotedMessageId])

  const handleSuggestionClick = useCallback(
    (value: string) => {
      if (isStreaming || isComposerDisabled) {
        return
      }
      submitMessage(value)
    },
    [isComposerDisabled, isStreaming, submitMessage],
  )

  const submitButtonDisabled = isStreaming
    ? false
    : !inputValue.trim() || status !== "ready" || isComposerDisabled
  const shouldShowScrollButton =
    showScrollButton && !isAwaitingAgentSelection && !isLoadingConversation

  // Handle quote action - set quoted content and message ID
  // Use message index as stable ID for jump functionality
  const handleQuote = useCallback((message: LocalChatMessage, messageIndex: number) => {
    setQuotedContent(message.content)
    // Use index as stable ID (works after page refresh)
    setQuotedMessageId(`msg-${messageIndex}`)
    // Focus the textarea
    const textarea = document.querySelector('textarea[name="message"]') as HTMLTextAreaElement
    textarea?.focus()
  }, [])

  // Clear quoted content
  const clearQuote = useCallback(() => {
    setQuotedContent(null)
    setQuotedMessageId(null)
  }, [])

  return (
    <section className="grid h-full min-h-0 min-w-0 flex-1 grid-rows-[minmax(0,1fr)_auto] overflow-hidden bg-background">
      <div
        className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background px-4 pb-2 md:px-6"
      >
        {appError ? (
          <Alert variant="destructive" className="mt-4">
            <AlertTitle>{t("chat.requestFailed")}</AlertTitle>
            <AlertDescription>{appError}</AlertDescription>
          </Alert>
        ) : null}

        <div className="relative min-h-0 flex-1">
          <div
            ref={conversationRef}
            className={[
              "chat-messages-scroll-area mx-auto h-full max-w-4xl overflow-y-auto",
              isMessagesScrolling ? "is-scrolling" : "",
            ].join(" ")}
            onScroll={updateScrollButtonState}
          >
            {isLoadingConversation ? (
              <div className=" flex h-full w-full items-center justify-center">
                <Loader size={32} />
              </div>
            ) : isAwaitingAgentSelection ? (
              <div className="grid min-h-full place-items-center px-2 py-6">
                <div className="mx-auto flex w-full max-w-4xl -translate-y-6 flex-col items-center gap-4 md:-translate-y-8">
                  <div className="w-full space-y-1 text-center">
                    <h1 className="mb-8 text-4xl font-semibold">{t("chat.chooseAgent")}</h1>
                  </div>

                  <AgentGrid
                    agents={agents}
                    selectedAgentId={selectedAgentId}
                    onSelectAgent={onSelectAgent}
                  />
                </div>
              </div>
            ) : (
              <div className="mx-auto flex w-full flex-col gap-4 pb-3 px-3 pt-8">
                {messages.length === 0 ? null : (
                  messages.map((message, index) => {
                    const isLastAIMessage = index === messages.length - 1 && message.type === "ai"

                    return (
                      <ChatMessageItem
                        key={`msg-${index}`}
                        message={{ ...message, local_id: `msg-${index}` }}
                        messageIndex={index}
                        calledTools={isLastAIMessage ? calledTools : []}
                        isAgentThinking={isLastAIMessage ? isAgentThinking : false}
                        thinkingContent={isLastAIMessage ? thinkingContent : ""}
                        isProcessing={isLastAIMessage && isProcessing}
                        isStreaming={message.is_streaming}
                        processSession={isLastAIMessage ? processSession : null}
                        messageSequence={isLastAIMessage ? messageSequence : undefined}
                        onEditMessage={onEditMessage}
                        editDisabled={isStreaming || isComposerDisabled}
                        onQuote={() => handleQuote(message, index)}
                        quoteDisabled={isStreaming || isComposerDisabled}
                        onJumpToMessage={onJumpToMessage}
                        onToggleSidebarProcess={onToggleSidebarProcess}
                      />
                    )
                  })
                )}
                <div ref={endOfMessagesRef} />
              </div>
            )}
          </div>
          {!isAwaitingAgentSelection ? (
            <div
              aria-hidden="true"
              className="chat-messages-bottom-fade pointer-events-none absolute inset-x-0 bottom-0 z-10 mx-auto h-8 max-w-4xl"
            />
          ) : null}

        </div>

      </div>

      {!isAwaitingAgentSelection ? (
        <footer className="relative  z-20 bg-background ">
          {shouldShowScrollButton ? (
            <Button
              size="icon"
              variant="secondary"
              className="absolute top-0 left-1/2 z-30 cursor-pointer -translate-x-1/2 -translate-y-1/2 rounded-full shadow-md"
              onClick={() => {
                autoScrollEnabledRef.current = true
                setShowScrollButton(false)
                scrollToBottom("smooth")
                if (isStreamingRef.current) {
                  startStreamFollow()
                }
              }}
            >
              <ArrowDown className="size-4" />
            </Button>
          ) : null}
          <div className="mx-auto w-full max-w-4xl space-y-3 overflow-y-auto p-2 mb-2">
            <div className="flex flex-wrap gap-2">
              {messages.length === 0 ? (
                suggestions.map((suggestion) => (
                  <Button
                    key={suggestion}
                    type="button"
                    size="sm"
                    variant="outline"
                    className="rounded-4 cursor-pointer"
                    onClick={() => handleSuggestionClick(suggestion)}
                    disabled={isStreaming || isComposerDisabled}
                  >
                    {suggestion}
                  </Button>
                ))
              ) : null}
            </div>

            <PromptInput
              className="h-auto min-h-12 bg-background [&_[data-slot=input-group]]:rounded-2xl"
              onSubmit={({ text }) => {
                submitMessage(text)
              }}
            >
              {/* Quoted content display above input */}
              {quotedContent ? (
                <div className="relative px-3 pt-3">
                  <div className="rounded-lg border border-border/60 bg-muted/30 p-3">
                    {/* Close button */}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="absolute top-2 right-2 size-5 cursor-pointer"
                      onClick={clearQuote}
                    >
                      <XIcon className="size-3" />
                    </Button>
                    {/* Quoted text - gray, show first 100 chars */}
                    <p className="text-sm text-muted-foreground whitespace-pre-wrap break-words line-clamp-3 pr-6">
                      {quotedContent.length > 100 ? `${quotedContent.slice(0, 100)}_` : quotedContent}
                    </p>
                  </div>
                  {/* Separator line */}
                  <Separator className="mt-3" />
                </div>
              ) : null}

              <PromptInputBody  >
                <PromptInputTextarea
                  className="max-h-26 min-h-8"
                  disabled={isComposerDisabled}
                  onChange={(event) => setInputValue(event.currentTarget.value)}
                  value={inputValue}
                  placeholder={quotedContent ? t("message.addYourMessage") : t("prompt.placeholder")}
                />
              </PromptInputBody>
              <PromptInputFooter className="pb-3 justify-between">
                <div className="flex items-center gap-2">
                  <ThinkingModeToggle
                    enabled={thinkingMode}
                    modelSupportsThinking={modelSupportsThinking}
                    onToggle={onToggleThinkingMode}
                  />
                </div>
                <PromptInputSubmit
                  disabled={submitButtonDisabled}
                  onClick={isStreaming ? onStopStreaming : undefined}
                  status={status}
                  className="cursor-pointer"
                  type={isStreaming ? "button" : "submit"}
                />
              </PromptInputFooter>
            </PromptInput>
          </div>
        </footer>
      ) : null}
    </section>
  )
}