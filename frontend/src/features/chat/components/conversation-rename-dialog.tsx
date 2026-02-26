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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit conversation title</DialogTitle>
          <DialogDescription>
            Update the selected conversation title (max 64 characters).
          </DialogDescription>
        </DialogHeader>

        <Input
          value={draftTitle}
          onChange={(event) => onDraftTitleChange(event.target.value)}
          maxLength={64}
          placeholder="Conversation title"
        />

        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={onSave} disabled={isSavingTitle}>
            {isSavingTitle ? (
              <>
                <LoaderCircle className="mr-2 size-4 animate-spin" />
                Saving
              </>
            ) : (
              "Save"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
