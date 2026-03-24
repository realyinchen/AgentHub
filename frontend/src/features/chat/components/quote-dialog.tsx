import { useState, useEffect, useRef } from "react"
import { useI18n } from "@/i18n"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Separator } from "@/components/ui/separator"

export interface QuoteDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  quotedContent: string
  onConfirm: (newContent: string) => void
  isLoading?: boolean
}

export function QuoteDialog({
  open,
  onOpenChange,
  quotedContent,
  onConfirm,
  isLoading = false,
}: QuoteDialogProps) {
  const { t } = useI18n()
  const [content, setContent] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Reset content when dialog opens
  useEffect(() => {
    if (open) {
      setContent("")
      // Focus textarea after a short delay
      setTimeout(() => {
        textareaRef.current?.focus()
      }, 100)
    }
  }, [open])

  const handleSubmit = () => {
    if (content.trim()) {
      onConfirm(content.trim())
      setContent("")
      onOpenChange(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{t("message.quoteDialog")}</DialogTitle>
          <DialogDescription>
            {t("message.quoteDescription")}
          </DialogDescription>
        </DialogHeader>
        
        {/* Preview of how the message will look */}
        <div className="rounded-lg border border-border bg-muted/30 p-3">
          {/* Quoted content - gray text */}
          <div className="text-sm text-muted-foreground whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
            {quotedContent}
          </div>
          
          {/* Separator line */}
          <Separator className="my-2" />
          
          {/* User input - preview */}
          <div className="text-sm whitespace-pre-wrap break-words min-h-[24px]">
            {content || <span className="text-muted-foreground italic">{t("message.quotePlaceholder")}</span>}
          </div>
        </div>

        {/* User input */}
        <div className="space-y-2">
          <Textarea
            ref={textareaRef}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("message.quotePlaceholder")}
            className="min-h-[80px] resize-none"
            disabled={isLoading}
          />
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
          >
            {t("common.cancel")}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!content.trim() || isLoading}
          >
            {isLoading ? t("common.loading") : t("common.send")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
