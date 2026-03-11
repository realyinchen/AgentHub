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
import { useI18n } from "@/i18n"

type DeleteConversationDialogProps = {
  open: boolean
  title?: string
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}

export function DeleteConversationDialog({
  open,
  title,
  onOpenChange,
  onConfirm,
}: DeleteConversationDialogProps) {
  const { t } = useI18n()

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("conversation.deleteTitle")}</AlertDialogTitle>
          <AlertDialogDescription>
            {title
              ? t("conversation.deleteDescriptionWithTitle", { title })
              : t("conversation.deleteDescriptionWithoutTitle")}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>{t("common.delete")}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
