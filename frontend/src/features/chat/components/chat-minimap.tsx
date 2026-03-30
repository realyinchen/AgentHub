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
  scrollContainerRef 
}: ChatMinimapProps) {
  const minimapRef = useRef<HTMLDivElement>(null)
  const [viewportHeight, setViewportHeight] = useState(VIEWPORT_MIN_HEIGHT)
  const [isDragging, setIsDragging] = useState(false)
  const [dragStartY, setDragStartY] = useState(0)
  const [scrollInfo, setScrollInfo] = useState({ scrollTop: 0, scrollHeight: 0, clientHeight: 0 })
  const [isHoveringMinimap, setIsHoveringMinimap] = useState(false)
  const [isHoveringTooltip, setIsHoveringTooltip] = useState(false)
  const hideTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Show viewport when hovering minimap or tooltip
  const showViewport = isHoveringMinimap || isHoveringTooltip || isDragging

  // Handle mouse enter on minimap
  const handleMinimapMouseEnter = useCallback(() => {
    if (hideTimeoutRef.current) {
      clearTimeout(hideTimeoutRef.current)
      hideTimeoutRef.current = null
    }
    setIsHoveringMinimap(true)
  }, [])

  // Handle mouse leave on minimap
  const handleMinimapMouseLeave = useCallback(() => {
    setIsHoveringMinimap(false)
  }, [])

  const handleTooltipMouseEnter = useCallback(() => {
    if (hideTimeoutRef.current) {
      clearTimeout(hideTimeoutRef.current)
      hideTimeoutRef.current = null
    }
    setIsHoveringTooltip(true)
  }, [])

  const handleTooltipMouseLeave = useCallback(() => {
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
  const generateMiniLines = useCallback(() => {
    const lines: Array<{
      localId: string
      type: string
      content: string
      lineIndex: number
      messageIndex: number
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
          localId: `msg-${messageIndex}`,
          type: message.type,
          content: line,
          lineIndex: idx,
          messageIndex: messageIndex,
        })
      })
    })

    return lines
  }, [messages])

  const miniLines = generateMiniLines()
  const totalLinesHeight = miniLines.length * LINE_HEIGHT + PADDING * 2

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

  // Calculate minimap content offset to keep viewport visible
  // This implements VSCode-style minimap scrolling
  const getMinimapContentOffset = useCallback(() => {
    if (scrollInfo.scrollHeight === 0 || totalLinesHeight === 0) return 0
    
    const minimapHeight = minimapRef.current?.clientHeight || 0
    if (minimapHeight === 0) return 0
    
    // Calculate the scale between minimap and main content
    const scale = totalLinesHeight / scrollInfo.scrollHeight
    
    // Viewport height in minimap space
    const viewportHeightPx = Math.max(VIEWPORT_MIN_HEIGHT, scrollInfo.clientHeight * scale)
    
    // Viewport top position in minimap space (without offset)
    const viewportTopPx = scrollInfo.scrollTop * scale
    
    // Calculate the offset needed to keep viewport within minimap bounds
    // The viewport should always be visible in the minimap
    const maxViewportTop = minimapHeight - viewportHeightPx
    
    // If viewport would go below the minimap, offset the content up
    if (viewportTopPx > maxViewportTop) {
      return -(viewportTopPx - maxViewportTop)
    }
    
    return 0
  }, [scrollInfo, totalLinesHeight])

  // Update viewport height based on actual scroll position
  useEffect(() => {
    if (scrollInfo.scrollHeight === 0 || totalLinesHeight === 0) return

    const scale = totalLinesHeight / scrollInfo.scrollHeight
    const viewportHeightPx = Math.max(VIEWPORT_MIN_HEIGHT, scrollInfo.clientHeight * scale)
    setViewportHeight(viewportHeightPx)
  }, [scrollInfo, totalLinesHeight])

  // Get viewport position relative to minimap visible area
  const getViewportPosition = useCallback(() => {
    if (scrollInfo.scrollHeight === 0 || totalLinesHeight === 0) return { top: 0, height: VIEWPORT_MIN_HEIGHT }
    
    const minimapHeight = minimapRef.current?.clientHeight || 0
    if (minimapHeight === 0) return { top: 0, height: viewportHeight }
    
    const scale = totalLinesHeight / scrollInfo.scrollHeight
    const viewportTopPx = scrollInfo.scrollTop * scale
    const contentOffset = getMinimapContentOffset()
    
    // Viewport position relative to minimap visible area
    const viewportTop = viewportTopPx + contentOffset
    
    return { top: viewportTop, height: viewportHeight }
  }, [scrollInfo, totalLinesHeight, viewportHeight, getMinimapContentOffset])

  // Get visible messages for viewport preview based on actual scroll position
  const visibleMessages = useCallback(() => {
    if (miniLines.length === 0 || messages.length === 0 || scrollInfo.scrollHeight === 0) return []
    
    const scale = totalLinesHeight / scrollInfo.scrollHeight
    const visibleTop = scrollInfo.scrollTop
    const visibleBottom = scrollInfo.scrollTop + scrollInfo.clientHeight
    
    const visibleLineIndices: number[] = []
    miniLines.forEach((_, index) => {
      const lineTop = PADDING + index * LINE_HEIGHT
      const lineBottom = lineTop + LINE_HEIGHT
      
      const mainContentTop = lineTop / scale
      const mainContentBottom = lineBottom / scale
      
      if (mainContentBottom > visibleTop && mainContentTop < visibleBottom) {
        visibleLineIndices.push(index)
      }
    })
    
    const visibleMessageIndices = new Set<number>()
    visibleLineIndices.forEach(idx => {
      const localId = miniLines[idx].localId
      const match = localId.match(/^msg-(\d+)$/)
      if (match) {
        visibleMessageIndices.add(parseInt(match[1], 10))
      }
    })
    
    return messages.filter((msg, index) => 
      visibleMessageIndices.has(index) && msg.type !== 'tool'
    )
  }, [miniLines, messages, scrollInfo, totalLinesHeight])()

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

  // Handle click on minimap - scroll to the clicked position
  const handleMinimapClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const minimap = minimapRef.current
    const container = scrollContainerRef.current
    if (!minimap || !container || scrollInfo.scrollHeight === 0) return

    const rect = minimap.getBoundingClientRect()
    const clickY = e.clientY - rect.top - PADDING
    
    const scale = scrollInfo.scrollHeight / totalLinesHeight
    
    // Account for content offset when calculating click position
    const contentOffset = getMinimapContentOffset()
    const adjustedClickY = clickY - contentOffset
    
    // Center the clicked position in the viewport
    const targetScrollTop = Math.max(0, adjustedClickY * scale - scrollInfo.clientHeight / 2)
    
    container.scrollTo({
      top: targetScrollTop,
      behavior: 'smooth'
    })
  }, [scrollContainerRef, scrollInfo.scrollHeight, scrollInfo.clientHeight, totalLinesHeight, getMinimapContentOffset])

  // Handle click on a specific line - scroll to that line's position
  const handleLineClick = useCallback((e: React.MouseEvent<HTMLDivElement>, lineIndex: number) => {
    e.stopPropagation()
    
    const container = scrollContainerRef.current
    if (!container || scrollInfo.scrollHeight === 0) return

    const lineTop = PADDING + lineIndex * LINE_HEIGHT
    const scale = scrollInfo.scrollHeight / totalLinesHeight
    
    // Center the line in the viewport
    const targetScrollTop = Math.max(0, lineTop * scale - scrollInfo.clientHeight / 2)
    
    container.scrollTo({
      top: targetScrollTop,
      behavior: 'smooth'
    })
  }, [scrollContainerRef, scrollInfo.scrollHeight, scrollInfo.clientHeight, totalLinesHeight])

  // Handle drag
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
    
    // Account for content offset
    const contentOffset = getMinimapContentOffset()
    const adjustedDragY = dragY - contentOffset
    
    // Center the viewport on the drag position
    const targetScrollTop = Math.max(0, adjustedDragY * scale - scrollInfo.clientHeight / 2)
    
    container.scrollTo({
      top: targetScrollTop,
      behavior: 'auto'
    })
  }, [isDragging, scrollContainerRef, scrollInfo.scrollHeight, scrollInfo.clientHeight, totalLinesHeight, getMinimapContentOffset])

  const handleDragEnd = useCallback((e: MouseEvent) => {
    const wasClick = Math.abs(e.clientY - dragStartY) < 5
    
    if (wasClick) {
      const minimap = minimapRef.current
      const container = scrollContainerRef.current
      if (minimap && container && scrollInfo.scrollHeight > 0) {
        const rect = minimap.getBoundingClientRect()
        const clickY = e.clientY - rect.top - PADDING
        const scale = scrollInfo.scrollHeight / totalLinesHeight
        
        const contentOffset = getMinimapContentOffset()
        const adjustedClickY = clickY - contentOffset
        
        const targetScrollTop = Math.max(0, adjustedClickY * scale - scrollInfo.clientHeight / 2)
        
        container.scrollTo({
          top: targetScrollTop,
          behavior: 'smooth'
        })
      }
    }
    
    setIsDragging(false)
  }, [dragStartY, scrollContainerRef, scrollInfo.scrollHeight, scrollInfo.clientHeight, totalLinesHeight, getMinimapContentOffset])

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

  const contentOffset = getMinimapContentOffset()
  const viewportPosition = getViewportPosition()

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
        onMouseEnter={handleMinimapMouseEnter}
        onMouseLeave={handleMinimapMouseLeave}
      >
        {/* Mini content - actual text like VSCode minimap */}
        {/* Content moves to keep viewport visible */}
        <div 
          className="absolute inset-0 overflow-hidden"
          style={{ padding: `${PADDING}px` }}
        >
          <div 
            className="absolute left-0 right-0"
            style={{ 
              top: `${PADDING + contentOffset}px`,
              height: `${totalLinesHeight}px`
            }}
          >
            {miniLines.map((line, index) => {
              const top = index * LINE_HEIGHT
              
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
                  onClick={(e) => handleLineClick(e, index)}
                  title={getPreviewText(line.content)}
                >
                  {line.content.slice(0, 60)}
                </div>
              )
            })}
          </div>
        </div>

        {/* Viewport indicator with preview - hidden by default, shown on hover */}
        <Tooltip open={showViewport && (isHoveringMinimap || isHoveringTooltip)}>
          <TooltipTrigger asChild>
            <div
              className={cn(
                "absolute left-0 right-0 bg-primary/10 dark:bg-primary/5",
                "border border-primary/30 rounded-sm",
                "cursor-grab transition-all duration-200",
                "hover:bg-primary/15 hover:border-primary/40",
                isDragging && "cursor-grabbing bg-primary/20",
                // Hidden by default, shown on hover
                !showViewport && "opacity-0",
                showViewport && "opacity-100"
              )}
              style={{
                top: `${viewportPosition.top}px`,
                height: `${viewportPosition.height}px`,
                minHeight: `${VIEWPORT_MIN_HEIGHT}px`,
              }}
              onMouseDown={handleViewportMouseDown}
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