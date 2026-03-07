import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ArrowDown, Languages, Moon, Share2, Sun } from "lucide-react"

import type { AgentInDB, LocalChatMessage, ToolCallEvent, ToolCallInfo } from "@/types"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai/prompt-input"
import { ChatMessageItem } from "@/features/chat/components/chat-message-item"
import { Loader } from "~/components/ai/loader"
import { useI18n } from "@/i18n"
import { useTheme } from "@/hooks/use-theme"

type ChatMainPanelProps = {
  agents: AgentInDB[]
  selectedAgentId: string
  appError: string | null
  isStreaming: boolean
  isInitializing: boolean
  isLoadingConversation: boolean
  isAwaitingAgentSelection: boolean
  isAgentThinking: boolean
  activeToolCall: ToolCallEvent | null
  calledTools: ToolCallInfo[]
  messages: LocalChatMessage[]
  onSendMessage: (rawInput: string) => Promise<void>
  onStopStreaming: () => void
  onSelectAgent: (agentId: string) => void
}

const SCROLL_BOTTOM_HIDE_THRESHOLD = 24
const SCROLL_BUTTON_SHOW_OFFSET = 180
const SCROLLBAR_FADE_OUT_DELAY = 420
const STREAM_SCROLL_EASING = 0.2
const STREAM_SCROLL_MIN_STEP = 1
const USER_SCROLL_INTERRUPT_DELTA = -2

export function ChatMainPanel({
  agents,
  selectedAgentId,
  appError,
  isStreaming,
  isInitializing,
  isLoadingConversation,
  isAwaitingAgentSelection,
  isAgentThinking,
  activeToolCall,
  calledTools,
  messages,
  onSendMessage,
  onStopStreaming,
  onSelectAgent,
}: ChatMainPanelProps) {
  const { t, toggleLocale } = useI18n()
  const { theme, toggleTheme } = useTheme()
  const [inputValue, setInputValue] = useState("")

  const endOfMessagesRef = useRef<HTMLDivElement | null>(null)
  const conversationRef = useRef<HTMLDivElement | null>(null)
  const scrollbarHideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const streamFollowRafRef = useRef<number | null>(null)
  const autoScrollEnabledRef = useRef(true)
  const isStreamingRef = useRef(isStreaming)
  const lastKnownScrollTopRef = useRef(0)
  const [showScrollButton, setShowScrollButton] = useState(false)
  const [isMessagesScrolling, setIsMessagesScrolling] = useState(false)
  const [showShareDialog, setShowShareDialog] = useState(false)

  const handleShare = useCallback(() => {
    const url = window.location.href
    navigator.clipboard.writeText(url).then(() => {
      setShowShareDialog(true)
    })
  }, [])

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

  const selectableAgents = useMemo(() => {
    if (agents.length === 0) {
      return [
        {
          agent_id: "chatbot",
          description: t("chat.defaultAssistant"),
        },
      ]
    }

    const mapped = agents.map((agent) => ({
      agent_id: agent.agent_id,
      description: agent.description || t("chat.noDescription"),
    }))

    // 当前选中的 agent 排在第一位，其余按原顺序排列
    const currentIndex = mapped.findIndex(
      (agent) => agent.agent_id === selectedAgentId
    )
    if (currentIndex > 0) {
      const current = mapped[currentIndex]
      const others = mapped.filter((_, index) => index !== currentIndex)
      return [current, ...others]
    }

    return mapped
  }, [agents, selectedAgentId, t])

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

    setInputValue("")
    void onSendMessage(trimmed)
  }, [isComposerDisabled, isStreaming, onSendMessage])

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
  const handleAgentChange = useCallback(
    (value: string) => {
      if (isStreaming || isComposerDisabled) {
        return
      }
      onSelectAgent(value)
    },
    [isComposerDisabled, isStreaming, onSelectAgent],
  )

  const getAgentDisplayName = useCallback(
    (agentId: string) => {
      if (agentId.toLowerCase().includes("rag")) {
        return t("chat.status.rag")
      }
      if (agentId === "chatbot") {
        return t("chat.status.chatbot")
      }
      return agentId
    },
    [t],
  )

  return (
    <section className="grid h-full min-h-0 min-w-0 flex-1 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden bg-background">
      <header className="z-20 flex w-full flex-col items-end gap-2 bg-background px-4 pt-3 md:px-6">
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="cursor-pointer gap-1.5"
            onClick={handleShare}
            aria-label={t("share.button")}
          >
            <Share2 className="size-4" />
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="cursor-pointer gap-1.5"
            onClick={toggleTheme}
            aria-label={t("theme.switch")}
          >
            {theme === "light" ? (
              <Sun className="size-4" />
            ) : (
              <Moon className="size-4" />
            )}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="cursor-pointer gap-1.5"
            onClick={toggleLocale}
            aria-label={t("language.switch")}
          >
            <Languages className="size-4" />
            {t("language.toggleLabel")}
          </Button>
        </div>
        {!isAwaitingAgentSelection ? (
          <Select
            value={selectedAgentId}
            onValueChange={handleAgentChange}
            disabled={isStreaming || isComposerDisabled}
          >
            <SelectTrigger className="w-40" size="sm">
              <SelectValue placeholder={t("chat.selectAgent")} />
            </SelectTrigger>
            <SelectContent>
              {selectableAgents.map((agent) => (
                <SelectItem key={agent.agent_id} value={agent.agent_id}>
                  {getAgentDisplayName(agent.agent_id)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </header>

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

                  <div className="mx-auto flex w-full flex-wrap justify-center gap-3">
                    {selectableAgents.map((agent) => (
                      <Card
                        key={agent.agent_id}
                        role="button"
                        tabIndex={0}
                        onClick={() => onSelectAgent(agent.agent_id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault()
                            onSelectAgent(agent.agent_id)
                          }
                        }}
                        className="w-full max-w-sm cursor-pointer gap-4 px-1 py-5 transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md md:basis-[calc(50%-0.375rem)] xl:basis-[calc(33.333%-0.5rem)]"
                      >
                        <CardHeader className="gap-2 px-5">
                          <CardTitle className="text-base">{agent.agent_id}</CardTitle>
                          <CardDescription className="line-clamp-3">
                            {agent.description}
                          </CardDescription>
                        </CardHeader>
                      </Card>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mx-auto flex w-full  flex-col gap-4 py-3 p-3 ">
                {messages.length === 0 ? null : (
                  messages.map((message, index) => {
                    const retrySource = message.type === "ai"
                      ? messages
                        .slice(0, index)
                        .reverse()
                        .find((candidate) => (
                          candidate.type === "human" && candidate.content.trim().length > 0
                        ))
                      : null

                    // Only show calledTools and thinking state on the last AI message
                    const isLastAIMessage = message.type === "ai" && index === messages.length - 1
                    const toolsForMessage = isLastAIMessage ? calledTools : []
                    const thinkingForMessage = isLastAIMessage ? isAgentThinking : false
                    const toolNameForMessage = isLastAIMessage ? activeToolCall?.name : null

                    return (
                      <ChatMessageItem
                        key={message.local_id}
                        message={message}
                        onRetry={retrySource ? () => submitMessage(retrySource.content) : undefined}
                        retryDisabled={isStreaming || isComposerDisabled}
                        calledTools={toolsForMessage}
                        isAgentThinking={thinkingForMessage}
                        activeToolName={toolNameForMessage}
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
              <PromptInputBody  >
                <PromptInputTextarea
                  className="max-h-26 min-h-8"
                  disabled={isComposerDisabled}
                  onChange={(event) => setInputValue(event.currentTarget.value)}
                  value={inputValue}
                  placeholder={t("prompt.placeholder")}
                />
              </PromptInputBody>
              <PromptInputFooter className="pb-3 justify-end">
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

      <Dialog open={showShareDialog} onOpenChange={setShowShareDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("share.title")}</DialogTitle>
            <DialogDescription>{t("share.description")}</DialogDescription>
          </DialogHeader>
        </DialogContent>
      </Dialog>
    </section>
  )
}
