import { useCallback, useEffect, useMemo, useState } from "react"
import { Brain, RefreshCw, Trash2 } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { getCurrentMemories, forgetMemory } from "@/lib/api"
import type { MemoryEvent } from "@/types"
import { useI18n } from "@/i18n"

type MemoryManagementDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  userId: string | null
}

function formatDate(value: string | null): string {
  if (!value) {
    return ""
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ""
  }
  return date.toLocaleString()
}

function tokenLabel(value: string): string {
  return value.replace(/_/g, " ")
}

export function MemoryManagementDialog({
  open,
  onOpenChange,
  userId,
}: MemoryManagementDialogProps) {
  const { t } = useI18n()
  const [memories, setMemories] = useState<MemoryEvent[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [forgettingId, setForgettingId] = useState<string | null>(null)

  const sortedMemories = useMemo(
    () =>
      memories
        .filter((memory) => !memory.forgotten && !memory.superseded_by)
        .sort((left, right) => {
          const leftTime = new Date(left.updated_at || left.created_at || 0).getTime()
          const rightTime = new Date(right.updated_at || right.created_at || 0).getTime()
          return rightTime - leftTime
        }),
    [memories],
  )

  const loadMemories = useCallback(async () => {
    if (!userId) {
      setMemories([])
      return
    }
    setIsLoading(true)
    setError(null)
    try {
      const result = await getCurrentMemories(userId)
      setMemories(result.memories)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t("error.unexpected"))
    } finally {
      setIsLoading(false)
    }
  }, [t, userId])

  useEffect(() => {
    if (open) {
      void loadMemories()
    }
  }, [loadMemories, open])

  const handleForget = useCallback(
    async (memory: MemoryEvent) => {
      if (!userId || !memory.id) {
        return
      }
      setForgettingId(memory.id)
      setError(null)
      try {
        await forgetMemory({
          user_id: userId,
          memory_id: memory.id,
          reason: "user forgot memory from current memory view",
        })
        setMemories((current) => current.filter((item) => item.id !== memory.id))
      } catch (forgetError) {
        setError(
          forgetError instanceof Error
            ? forgetError.message
            : t("memory.forgetFailed"),
        )
      } finally {
        setForgettingId(null)
      }
    },
    [t, userId],
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Brain className="size-5 text-[var(--primary)]" />
            {t("memory.currentTitle")}
          </DialogTitle>
          <DialogDescription>{t("memory.currentDescription")}</DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between gap-3">
          <div className="text-sm text-muted-foreground">
            {t("memory.total", { count: sortedMemories.length })}
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void loadMemories()}
            disabled={isLoading || !userId}
          >
            <RefreshCw className={`size-4 ${isLoading ? "animate-spin" : ""}`} />
            {t("common.refresh")}
          </Button>
        </div>

        {error && (
          <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-300">
            {error}
          </div>
        )}

        <div className="max-h-[55vh] overflow-y-auto pr-1">
          {isLoading && sortedMemories.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              {t("common.loading")}
            </div>
          ) : sortedMemories.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              {t("memory.currentEmpty")}
            </div>
          ) : (
            <div className="space-y-2">
              {sortedMemories.map((memory) => (
                <div
                  key={memory.id || `${memory.type}-${memory.subject}-${memory.value}`}
                  className="rounded-lg border border-border bg-background px-3 py-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{tokenLabel(memory.type)}</Badge>
                        <Badge variant="secondary">{tokenLabel(memory.subject)}</Badge>
                        <Badge
                          variant={
                            memory.polarity === "dislike" || memory.polarity === "avoid"
                              ? "destructive"
                              : memory.polarity === "like" || memory.polarity === "want"
                                ? "success"
                                : "outline"
                          }
                        >
                          {tokenLabel(memory.polarity)}
                        </Badge>
                      </div>
                      <p className="break-words text-sm font-medium leading-6">
                        {memory.value}
                      </p>
                      <div className="text-xs text-muted-foreground">
                        {t("memory.updatedAt", {
                          time: formatDate(memory.updated_at || memory.created_at) || "-",
                        })}
                      </div>
                    </div>
                    <Button
                      type="button"
                      size="icon"
                      variant="outline"
                      className="size-8 shrink-0 text-red-600 hover:border-red-500/40 hover:bg-red-500/10 hover:text-red-700 dark:text-red-300 dark:hover:text-red-200"
                      disabled={!memory.id || forgettingId === memory.id}
                      onClick={() => void handleForget(memory)}
                      aria-label={t("memory.forget")}
                      title={t("memory.forget")}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
