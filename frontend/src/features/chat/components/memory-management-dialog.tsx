import { useCallback, useEffect, useMemo, useState } from "react"
import { Brain, Check, RefreshCw, Trash2, X } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { confirmUserState, getCurrentMemories, forgetMemory } from "@/lib/api"
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
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})

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

  const handleConfirmation = useCallback(
    async (memory: MemoryEvent, accept: boolean) => {
      if (!userId || !memory.id) {
        return
      }
      setConfirmingId(memory.id)
      setError(null)
      try {
        const updated = await confirmUserState(memory.id, {
          user_id: userId,
          accept,
          summary: accept ? drafts[memory.id] || memory.value : undefined,
        })
        setMemories((current) =>
          accept
            ? current.map((item) => (item.id === memory.id ? updated : item))
            : current.filter((item) => item.id !== memory.id),
        )
      } catch (confirmationError) {
        setError(
          confirmationError instanceof Error
            ? confirmationError.message
            : t("error.unexpected"),
        )
      } finally {
        setConfirmingId(null)
      }
    },
    [drafts, t, userId],
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
                        <Badge variant="outline">
                          {tokenLabel(memory.state_category || memory.type)}
                        </Badge>
                        <Badge
                          variant={
                            memory.state_status === "needs_confirmation"
                              ? "destructive"
                              : memory.state_status === "active"
                                ? "success"
                                : "secondary"
                          }
                        >
                          {tokenLabel(memory.state_status)}
                        </Badge>
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
                      {memory.raw_text && memory.raw_text !== memory.value && (
                        <p className="break-words text-xs leading-5 text-muted-foreground">
                          原文：{memory.raw_text}
                        </p>
                      )}
                      {memory.use_when.length > 0 && (
                        <p className="break-words text-xs leading-5 text-muted-foreground">
                          使用场景：{memory.use_when.join("、")}
                        </p>
                      )}
                      {memory.state_status === "needs_confirmation" && memory.id && (
                        <div className="space-y-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-2">
                          <p className="text-xs text-amber-800 dark:text-amber-200">
                            {memory.confirmation_question || "请确认系统对这条记忆的理解。"}
                          </p>
                          <Textarea
                            className="min-h-16 rounded-md px-2 py-2 text-sm"
                            value={drafts[memory.id] ?? memory.value}
                            onChange={(event) =>
                              setDrafts((current) => ({
                                ...current,
                                [memory.id as string]: event.target.value,
                              }))
                            }
                          />
                          <div className="flex justify-end gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={confirmingId === memory.id}
                              onClick={() => void handleConfirmation(memory, false)}
                            >
                              <X className="size-4" />
                              不正确
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              disabled={confirmingId === memory.id}
                              onClick={() => void handleConfirmation(memory, true)}
                            >
                              <Check className="size-4" />
                              确认
                            </Button>
                          </div>
                        </div>
                      )}
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
