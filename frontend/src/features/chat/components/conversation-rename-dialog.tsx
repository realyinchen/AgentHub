import { LoaderCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { useI18n } from "@/i18n"

type ConversationRenameDialogProps = {
  open: boolean
  draftTitle: string
  isSavingTitle: boolean
  onOpenChange: (open: boolean) => void
  onDraftTitleChange: (value: string) => void
  onCancel: () => void
  onSave: () => void
}

export function ConversationRenameDialog({
  open,
  draftTitle,
  isSavingTitle,
  onOpenChange,
  onDraftTitleChange,
  onCancel,
  onSave,
}: ConversationRenameDialogProps) {
  const { t } = useI18n()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("conversation.editTitle")}</DialogTitle>
          <DialogDescription>
            {t("conversation.editDescription")}
          </DialogDescription>
        </DialogHeader>

        <Input
          value={draftTitle}
          onChange={(event) => onDraftTitleChange(event.target.value)}
          maxLength={64}
          placeholder={t("conversation.titlePlaceholder")}
        />

        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button onClick={onSave} disabled={isSavingTitle}>
            {isSavingTitle ? (
              <>
                <LoaderCircle className="mr-2 size-4 animate-spin" />
                {t("common.saving")}
              </>
            ) : (
              t("common.save")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
