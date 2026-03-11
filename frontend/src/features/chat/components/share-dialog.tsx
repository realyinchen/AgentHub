import { Check } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useI18n } from "@/i18n"

type ShareDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ShareDialog({ open, onOpenChange }: ShareDialogProps) {
  const { t } = useI18n()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Check className="size-5 text-green-500" />
            {t("share.title")}
          </DialogTitle>
          <DialogDescription className="pt-2">
            {t("share.description")}
          </DialogDescription>
        </DialogHeader>
        <div className="mt-2 rounded-lg bg-muted p-3">
          <p className="text-sm text-muted-foreground">
            {t("share.privacyWarning")}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  )
}