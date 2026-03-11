import { useCallback, useEffect, useRef, useState } from "react"
import { ChevronDown, ChevronUp } from "lucide-react"

import type { LocalChatMessage } from "@/types"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

type MessageRulerProps = {
  messages: LocalChatMessage[]
  onJumpToMessage: (localId: string) => void
}

const TICK_SPACING = 16 // Fixed spacing
const LONG_TICK_WIDTH = 12 // Long tick width
const SHORT_TICK_WIDTH = 6 // Short tick width
const TICK_HEIGHT = 2
const SCROLL_STEP = 60

export function MessageRuler({ messages, onJumpToMessage }: MessageRulerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [canScrollUp, setCanScrollUp] = useState(false)
  const [canScrollDown, setCanScrollDown] = useState(false)
  const hasCenteredRef = useRef(false)

  // Filter user messages
  const userMessages = messages.filter((msg) => msg.type === "human")

  // Check scroll state
  const checkScrollState = useCallback(() => {
    const container = containerRef.current
    if (!container) return

    const { scrollTop, scrollHeight, clientHeight } = container
    setCanScrollUp(scrollTop > 0)
    setCanScrollDown(scrollTop < scrollHeight - clientHeight - 1)
  }, [])

  // Center ruler
  const centerRuler = useCallback(() => {
    const container = containerRef.current
    if (!container) return

    const { scrollHeight, clientHeight } = container
    if (scrollHeight > clientHeight) {
      const centerScrollTop = (scrollHeight - clientHeight) / 2
      container.scrollTop = centerScrollTop
    }
  }, [])

  // Center when messages change - use setTimeout to ensure DOM is fully rendered
  useEffect(() => {
    if (userMessages.length === 0) return

    // Center after DOM is fully rendered
    const timerId = setTimeout(() => {
      centerRuler()
      hasCenteredRef.current = true
    }, 100)

    return () => {
      clearTimeout(timerId)
    }
  }, [userMessages.length, centerRuler])

  // Monitor container size changes
  useEffect(() => {
    checkScrollState()
    
    const container = containerRef.current
    if (!container) return

    const resizeObserver = new ResizeObserver(checkScrollState)
    resizeObserver.observe(container)
    
    return () => {
      resizeObserver.disconnect()
    }
  }, [userMessages.length, checkScrollState])

  // Scroll ruler up
  const scrollUp = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    container.scrollBy({ top: -SCROLL_STEP, behavior: "smooth" })
  }, [])

  // Scroll ruler down
  const scrollDown = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    container.scrollBy({ top: SCROLL_STEP, behavior: "smooth" })
  }, [])

  // Truncate message preview
  const getPreviewText = useCallback((content: string, maxLength = 50) => {
    const text = content.trim().replace(/\n/g, " ")
    if (text.length <= maxLength) return text
    return text.slice(0, maxLength) + "..."
  }, [])

  if (userMessages.length === 0) {
    return null
  }

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex flex-col items-center py-2 w-[20px] shrink-0">
        {/* Up arrow */}
        {canScrollUp && (
          <button
            type="button"
            onClick={scrollUp}
            className="mb-1 cursor-pointer text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Scroll up"
          >
            <ChevronUp className="size-3" />
          </button>
        )}

        {/* Ruler container */}
        <div
          ref={containerRef}
          className="flex-1 overflow-y-auto overflow-x-hidden scrollbar-hide min-h-0"
          onScroll={checkScrollState}
          style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}
        >
          {/* Use flexbox to center content */}
          <div className="flex flex-col min-h-full">
            {/* Top flex space */}
            <div className="flex-1" />
            <div
              className="flex flex-col items-center"
              style={{ gap: `${TICK_SPACING - TICK_HEIGHT}px` }}
            >
              {userMessages.map((message, index) => {
                const isLong = index % 2 === 0
                const tickWidth = isLong ? LONG_TICK_WIDTH : SHORT_TICK_WIDTH
                const previewText = getPreviewText(message.content)

                return (
                  <Tooltip key={message.local_id}>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        onClick={() => onJumpToMessage(message.local_id)}
                        className={cn(
                          "cursor-pointer rounded-sm transition-all duration-200 ease-out",
                          "bg-muted-foreground/40 hover:bg-primary/60",
                          "hover:scale-150 hover:shadow-sm",
                          "focus:outline-none focus:ring-1 focus:ring-primary"
                        )}
                        style={{
                          width: `${tickWidth}px`,
                          height: `${TICK_HEIGHT}px`,
                        }}
                        aria-label={`Jump to message: ${previewText}`}
                      />
                    </TooltipTrigger>
                    <TooltipContent
                      side="left"
                      sideOffset={8}
                      className="max-w-[200px] text-xs"
                    >
                      <p className="line-clamp-3">{previewText}</p>
                    </TooltipContent>
                  </Tooltip>
                )
              })}
            </div>
            {/* Bottom flex space */}
            <div className="flex-1" />
          </div>
        </div>

        {/* Down arrow */}
        {canScrollDown && (
          <button
            type="button"
            onClick={scrollDown}
            className="mt-1 cursor-pointer text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Scroll down"
          >
            <ChevronDown className="size-3" />
          </button>
        )}
      </div>
    </TooltipProvider>
  )
}