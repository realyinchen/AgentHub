import { ChevronLeft, ChevronRight } from "lucide-react"
import { useState } from "react"
import { cn } from "@/lib/utils"
import type { MessageNode } from "@/types/message-tree"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useI18n } from "@/i18n"

export interface BranchSelectorProps {
  siblings: MessageNode[]
  currentIndex: number
  onSelect: (nodeId: string) => void
  disabled?: boolean
}

export function BranchSelector({
  siblings,
  currentIndex,
  onSelect,
  disabled = false,
}: BranchSelectorProps) {
  const { t } = useI18n()
  const [isOpen, setIsOpen] = useState(false)

  if (siblings.length <= 1) {
    return null
  }

  // currentNode is available for future use (e.g., showing current branch info)
  // const currentNode = siblings[currentIndex]
  const hasPrev = currentIndex > 0
  const hasNext = currentIndex < siblings.length - 1
  const totalVersions = siblings.length

  const handlePrev = () => {
    if (hasPrev) {
      onSelect(siblings[currentIndex - 1].id)
    }
  }

  const handleNext = () => {
    if (hasNext) {
      onSelect(siblings[currentIndex + 1].id)
    }
  }

  // Format timestamp for display
  const formatTime = (dateString: string) => {
    try {
      const date = new Date(dateString)
      return date.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
      })
    } catch {
      return ""
    }
  }

  // Get a preview of content (first 50 chars)
  const getContentPreview = (content: string) => {
    const preview = content.trim().slice(0, 50)
    return preview.length < content.trim().length ? `${preview}...` : preview
  }

  return (
    <div className="flex items-center gap-1">
      {/* Previous button */}
      <Button
        variant="ghost"
        size="icon"
        className="size-6"
        onClick={handlePrev}
        disabled={!hasPrev || disabled}
        title={t("branch.previous")}
      >
        <ChevronLeft className="size-3" />
      </Button>

      {/* Version indicator / dropdown */}
      <DropdownMenu open={isOpen} onOpenChange={setIsOpen}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs text-muted-foreground"
            disabled={disabled}
          >
            {t("branch.version", { current: currentIndex + 1, total: totalVersions })}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="min-w-[200px]">
          {siblings.map((sibling, index) => (
            <DropdownMenuItem
              key={sibling.id}
              onClick={() => {
                onSelect(sibling.id)
                setIsOpen(false)
              }}
              className={cn(
                "flex flex-col items-start gap-0.5",
                index === currentIndex && "bg-accent"
              )}
            >
              <div className="flex items-center gap-2">
                <span className="font-medium">
                  {t("branch.versionLabel", { number: index + 1 })}
                </span>
                <span className="text-xs text-muted-foreground">
                  {formatTime(sibling.created_at)}
                </span>
              </div>
              <span className="text-xs text-muted-foreground line-clamp-1">
                {getContentPreview(sibling.content)}
              </span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Next button */}
      <Button
        variant="ghost"
        size="icon"
        className="size-6"
        onClick={handleNext}
        disabled={!hasNext || disabled}
        title={t("branch.next")}
      >
        <ChevronRight className="size-3" />
      </Button>
    </div>
  )
}