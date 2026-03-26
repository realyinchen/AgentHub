import { useCallback, useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import type { LocalChatMessage } from "@/types"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { MarkdownContent } from "@/components/ui/markdown-content"

type ChatMinimapProps = {
  messages: LocalChatMessage[]
  onJumpToMessage: (localId: string) => void
  scrollContainerRef: React.RefObject<HTMLDivElement | null>
}

// Minimap configuration - similar to VSCode minimap
const MINIMAP_WIDTH = 100
const FONT_SIZE = 2.5 // Very small font size in pixels
const LINE_HEIGHT = 3.5 // Line height in pixels
const VIEWPORT_MIN_HEIGHT = 30
const PADDING = 4

export function ChatMinimap({ 
  messages, 
  onJumpToMessage,
  scrollContainerRef 
}: ChatMinimapProps) {
  const minimapRef = useRef<HTMLDivElement>(null)
  const [viewportTop, setViewportTop] = useState(0)
  const [viewportHeight, setViewportHeight] = useState(VIEWPORT_MIN_HEIGHT)
  const [isDragging, setIsDragging] = useState(false)
  const [dragStartY, setDragStartY] = useState(0)
  const [scrollInfo, setScrollInfo] = useState({ scrollTop: 0, scrollHeight: 0, clientHeight: 0 })
  const [isHoveringViewport, setIsHoveringViewport] = useState(false)
  const [isHoveringTooltip, setIsHoveringTooltip] = useState(false)
  const hideTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Combined hover state - show tooltip if hovering either viewport or tooltip content
  const showTooltip = isHoveringViewport || isHoveringTooltip

  // Handle mouse enter with clearing any pending hide timeout
  const handleViewportMouseEnter = useCallback(() => {
    if (hideTimeoutRef.current) {
      clearTimeout(hideTimeoutRef.current)
      hideTimeoutRef.current = null
    }
    setIsHoveringViewport(true)
  }, [])

  const handleTooltipMouseEnter = useCallback(() => {
    if (hideTimeoutRef.current) {
      clearTimeout(hideTimeoutRef.current)
      hideTimeoutRef.current = null
    }
    setIsHoveringTooltip(true)
  }, [])

  // Handle mouse leave with delay to allow moving to tooltip
  const handleViewportMouseLeave = useCallback(() => {
    // Immediately set hovering to false, but delay hiding the tooltip
    // to allow time for mouse to move to tooltip
    setIsHoveringViewport(false)
  }, [])

  const handleTooltipMouseLeave = useCallback(() => {
    // Immediately set hovering to false
    setIsHoveringTooltip(false)
  }, [])

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (hideTimeoutRef.current) {
        clearTimeout(hideTimeoutRef.current)
      }
    }
  }, [])

  // Generate mini lines from messages directly
  // Use index-based local_id to match ChatMainPanel's rendering
  const generateMiniLines = useCallback(() => {
    const lines: Array<{
      localId: string
      type: string
      content: string
      lineIndex: number
    }> = []

    messages.forEach((message, messageIndex) => {
      // Skip tool messages
      if (message.type === 'tool') return
      
      // Split content into lines
      const contentLines = message.content.split('\n')
      
      contentLines.forEach((line, idx) => {
        // Skip completely empty lines
        if (line.trim() === '' && idx !== 0) return
        
        lines.push({
          // Use index-based ID to match ChatMainPanel's rendering: msg-${index}
          localId: `msg-${messageIndex}`,
          type: message.type,
          content: line,
          lineIndex: idx,
        })
      })
    })

    return lines
  }, [messages])

  const miniLines = generateMiniLines()
  const totalLinesHeight = miniLines.length * LINE_HEIGHT + PADDING * 2

  // Get visible messages for viewport preview based on minimap viewport position
  const getVisibleMessages = useCallback(() => {
    if (miniLines.length === 0 || messages.length === 0) return []
    
    // Calculate which mini lines are visible based on viewport position in minimap
    const viewportBottom = viewportTop + viewportHeight
    
    // Find the indices of mini lines that are within the viewport
    const visibleLineIndices: number[] = []
    miniLines.forEach((_, index) => {
      const lineTop = PADDING + index * LINE_HEIGHT
      const lineBottom = lineTop + LINE_HEIGHT
      
      // Check if line overlaps with viewport
      if (lineBottom > viewportTop && lineTop < viewportBottom) {
        visibleLineIndices.push(index)
      }
    })
    
    // Get unique message indices from visible lines
    // localId format is "msg-${messageIndex}"
    const visibleMessageIndices = new Set<number>()
    visibleLineIndices.forEach(idx => {
      const localId = miniLines[idx].localId
      // Extract message index from localId (format: "msg-${index}")
      const match = localId.match(/^msg-(\d+)$/)
      if (match) {
        visibleMessageIndices.add(parseInt(match[1], 10))
      }
    })
    
    // Find the corresponding messages by index
    return messages.filter((msg, index) => 
      visibleMessageIndices.has(index) && msg.type !== 'tool'
    )
  }, [miniLines, messages, viewportTop, viewportHeight])

  const visibleMessages = getVisibleMessages()

  // Update scroll info
  const updateScrollInfo = useCallback(() => {
    const container = scrollContainerRef.current
    if (!container) return

    setScrollInfo({
      scrollTop: container.scrollTop,
      scrollHeight: container.scrollHeight,
      clientHeight: container.clientHeight,
    })
  }, [scrollContainerRef])

  // Update viewport position
  useEffect(() => {
    if (scrollInfo.scrollHeight === 0 || totalLinesHeight === 0) return

    const scale = totalLinesHeight / scrollInfo.scrollHeight
    const viewportTopPx = scrollInfo.scrollTop * scale
    const viewportHeightPx = Math.max(VIEWPORT_MIN_HEIGHT, scrollInfo.clientHeight * scale)

    setViewportTop(viewportTopPx)
    setViewportHeight(viewportHeightPx)
  }, [scrollInfo, totalLinesHeight])

  // Setup scroll listener
  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return

    updateScrollInfo()
    container.addEventListener('scroll', updateScrollInfo)
    
    const resizeObserver = new ResizeObserver(updateScrollInfo)
    resizeObserver.observe(container)

    return () => {
      container.removeEventListener('scroll', updateScrollInfo)
      resizeObserver.disconnect()
    }
  }, [scrollContainerRef, updateScrollInfo])

  // Handle click on minimap
  const handleMinimapClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const minimap = minimapRef.current
    const container = scrollContainerRef.current
    if (!minimap || !container || scrollInfo.scrollHeight === 0) return

    const rect = minimap.getBoundingClientRect()
    const clickY = e.clientY - rect.top - PADDING
    
    const scale = scrollInfo.scrollHeight / totalLinesHeight
    const targetScrollTop = clickY * scale
    
    container.scrollTo({
      top: targetScrollTop,
      behavior: 'smooth'
    })
  }, [scrollContainerRef, scrollInfo.scrollHeight, totalLinesHeight])

  // Handle drag - with click detection
  const handleViewportMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
    setDragStartY(e.clientY)
  }, [])

  const handleDragMove = useCallback((e: MouseEvent) => {
    if (!isDragging) return

    const minimap = minimapRef.current
    const container = scrollContainerRef.current
    if (!minimap || !container || scrollInfo.scrollHeight === 0) return

    const rect = minimap.getBoundingClientRect()
    const dragY = e.clientY - rect.top - PADDING
    const scale = scrollInfo.scrollHeight / totalLinesHeight
    
    container.scrollTo({
      top: dragY * scale,
      behavior: 'auto'
    })
  }, [isDragging, scrollContainerRef, scrollInfo.scrollHeight, totalLinesHeight])

  const handleDragEnd = useCallback((e: MouseEvent) => {
    // Check if this was a click (minimal movement)
    const wasClick = Math.abs(e.clientY - dragStartY) < 5
    
    if (wasClick && !isDragging) {
      // This shouldn't happen, but just in case
      return
    }
    
    if (wasClick) {
      // It was a click, scroll to the clicked position
      const minimap = minimapRef.current
      const container = scrollContainerRef.current
      if (minimap && container && scrollInfo.scrollHeight > 0) {
        const rect = minimap.getBoundingClientRect()
        const clickY = e.clientY - rect.top - PADDING
        const scale = scrollInfo.scrollHeight / totalLinesHeight
        
        container.scrollTo({
          top: clickY * scale,
          behavior: 'smooth'
        })
      }
    }
    
    setIsDragging(false)
  }, [dragStartY, isDragging, scrollContainerRef, scrollInfo.scrollHeight, totalLinesHeight])

  useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', handleDragMove)
      window.addEventListener('mouseup', handleDragEnd)
      return () => {
        window.removeEventListener('mousemove', handleDragMove)
        window.removeEventListener('mouseup', handleDragEnd)
      }
    }
  }, [isDragging, handleDragMove, handleDragEnd])

  // Truncate for tooltip
  const getPreviewText = useCallback((content: string, maxLength = 100) => {
    const text = content.trim().replace(/\n/g, " ")
    if (text.length <= maxLength) return text
    return text.slice(0, maxLength) + "..."
  }, [])

  if (messages.length === 0) {
    return null
  }

  return (
    <TooltipProvider delayDuration={300}>
      <div 
        ref={minimapRef}
        className={cn(
          "relative flex-shrink-0 bg-muted/30 dark:bg-muted/20",
          "border-l border-r border-border/50",
          "cursor-pointer select-none overflow-hidden",
          isDragging && "cursor-grabbing"
        )}
        style={{ width: `${MINIMAP_WIDTH}px`, height: '100%' }}
        onClick={handleMinimapClick}
      >
        {/* Mini content - actual text like VSCode minimap */}
        <div 
          className="absolute inset-0 overflow-hidden"
          style={{ padding: `${PADDING}px` }}
        >
          {miniLines.map((line, index) => {
            const top = PADDING + index * LINE_HEIGHT
            
            return (
              <div
                key={`${line.localId}-${index}`}
                className={cn(
                  "absolute left-1 right-1 cursor-pointer whitespace-nowrap overflow-hidden",
                  "hover:bg-primary/10 transition-colors"
                )}
                style={{
                  top: `${top}px`,
                  height: `${LINE_HEIGHT}px`,
                  fontSize: `${FONT_SIZE}px`,
                  lineHeight: `${LINE_HEIGHT}px`,
                  fontFamily: 'monospace',
                  color: line.type === 'human' 
                    ? 'rgba(6, 182, 212, 0.7)' // cyan for user
                    : 'rgba(139, 92, 246, 0.7)', // violet for AI
                }}
                onClick={(e) => {
                  e.stopPropagation()
                  onJumpToMessage(line.localId)
                }}
                title={getPreviewText(line.content)}
              >
                {line.content.slice(0, 60)}
              </div>
            )
          })}
        </div>

        {/* Viewport indicator with preview */}
        <Tooltip open={showTooltip}>
          <TooltipTrigger asChild>
            <div
              className={cn(
                "absolute left-0 right-0 bg-primary/10 dark:bg-primary/5",
                "border border-primary/30 rounded-sm",
                "cursor-grab transition-colors",
                "hover:bg-primary/15 hover:border-primary/40",
                isDragging && "cursor-grabbing bg-primary/20"
              )}
              style={{
                top: `${viewportTop}px`,
                height: `${viewportHeight}px`,
                minHeight: `${VIEWPORT_MIN_HEIGHT}px`,
              }}
              onMouseDown={handleViewportMouseDown}
              onMouseEnter={handleViewportMouseEnter}
              onMouseLeave={handleViewportMouseLeave}
            />
          </TooltipTrigger>
          <TooltipContent
            side="left"
            sideOffset={8}
            className="max-w-[400px] max-h-[300px] overflow-y-auto p-3"
            onMouseEnter={handleTooltipMouseEnter}
            onMouseLeave={handleTooltipMouseLeave}
          >
            <div className="space-y-3">
              <div className="text-muted-foreground text-xs mb-2 font-medium">当前可见区域</div>
              {visibleMessages.length > 0 ? (
                visibleMessages.slice(0, 5).map((msg) => (
                  <div 
                    key={msg.local_id} 
                    className={cn(
                      "p-2 rounded-md text-sm",
                      msg.type === 'human' 
                        ? "bg-cyan-500/10 border border-cyan-500/20" 
                        : "bg-violet-500/10 border border-violet-500/20"
                    )}
                  >
                    <div className={cn(
                      "font-medium mb-1 text-xs",
                      msg.type === 'human' 
                        ? "text-cyan-600 dark:text-cyan-400" 
                        : "text-violet-600 dark:text-violet-400"
                    )}>
                      {msg.type === 'human' ? '👤 用户' : '🤖 AI'}
                    </div>
                    <div className="prose prose-sm dark:prose-invert max-w-none text-xs">
                      {msg.type === 'human' ? (
                        <div className="whitespace-pre-wrap break-words line-clamp-4">
                          {msg.content}
                        </div>
                      ) : (
                        <div className="minimap-preview">
                          <MarkdownContent content={msg.content} />
                        </div>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-muted-foreground text-sm">暂无消息</div>
              )}
              {visibleMessages.length > 5 && (
                <div className="text-muted-foreground text-xs text-center pt-1 border-t">
                  还有 {visibleMessages.length - 5} 条消息...
                </div>
              )}
            </div>
          </TooltipContent>
        </Tooltip>
      </div>
    </TooltipProvider>
  )
}