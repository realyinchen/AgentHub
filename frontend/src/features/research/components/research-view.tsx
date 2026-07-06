import { useCallback, useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  CircleStop,
  ExternalLink,
  FileText,
  Loader2,
  RefreshCw,
  Route,
  SearchCheck,
  ShieldCheck,
  XCircle,
} from "lucide-react"

import {
  cancelResearchRun,
  getResearchState,
  listResearchRuns,
} from "@/lib/api"
import type {
  ResearchEvidence,
  ResearchRun,
  ResearchRunStatus,
  ResearchStateResult,
  ResearchStep,
} from "@/types"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"

type ResearchViewProps = {
  userId: string | null
}

type AdmissionSummary = {
  admitted: number
  rejected: number
  uncertain: number
  ready: boolean | null
}

const FILTERS: Array<{ label: string; value: ResearchRunStatus | "" }> = [
  { label: "All", value: "" },
  { label: "Active", value: "active" },
  { label: "Completed", value: "completed" },
  { label: "Stopped", value: "cancelled" },
  { label: "Failed", value: "failed" },
]

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function formatDate(value: string | null): string {
  if (!value) {
    return "Not recorded"
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}

function statusBadge(status: string): "default" | "secondary" | "destructive" | "outline" | "success" {
  if (status === "completed") {
    return "success"
  }
  if (status === "failed") {
    return "destructive"
  }
  if (status === "cancelled") {
    return "outline"
  }
  if (status === "active") {
    return "default"
  }
  return "secondary"
}

function qualityBadge(quality: string): "default" | "secondary" | "destructive" | "outline" | "success" {
  if (quality === "high") {
    return "success"
  }
  if (quality === "medium") {
    return "default"
  }
  if (quality === "low") {
    return "destructive"
  }
  return "outline"
}

function finalConclusion(result: ResearchStateResult | null): string {
  if (!result) {
    return ""
  }
  const finishStep = [...result.steps]
    .reverse()
    .find((step) => step.step_type === "finish")
  return textValue(finishStep?.output?.conclusion)
}

function admissionSummary(result: ResearchStateResult | null): AdmissionSummary {
  const metadata = asRecord(result?.state.metadata)
  const admission = asRecord(metadata.admission)
  const harness = asRecord(metadata.harness)
  return {
    admitted: asArray(admission.admitted_claims).length
      || Number(harness.admitted_claim_count ?? 0),
    rejected: asArray(admission.rejected_claims).length
      || Number(harness.rejected_claim_count ?? 0),
    uncertain: asArray(admission.uncertain_claims).length
      || Number(harness.uncertain_claim_count ?? 0),
    ready: typeof admission.ready_for_final_answer === "boolean"
      ? admission.ready_for_final_answer
      : typeof harness.ready_for_final_answer === "boolean"
        ? harness.ready_for_final_answer
        : null,
  }
}

function JsonPreview({ value }: { value: unknown }) {
  if (value === undefined || value === null || value === "") {
    return null
  }
  return (
    <pre className="max-h-36 overflow-auto rounded-md border border-border/60 bg-muted/30 p-2 text-xs leading-relaxed text-muted-foreground">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

function ListBlock({
  title,
  items,
  empty,
  icon,
}: {
  title: string
  items: string[]
  empty: string
  icon: React.ReactNode
}) {
  return (
    <section className="min-h-32 rounded-lg border border-border/70 bg-background p-3">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        {icon}
        <span>{title}</span>
        <Badge variant="secondary" className="ml-auto px-2">
          {items.length}
        </Badge>
      </div>
      {items.length > 0 ? (
        <ul className="space-y-2 text-sm">
          {items.map((item, index) => (
            <li key={`${title}-${index}`} className="leading-relaxed text-foreground">
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{empty}</p>
      )}
    </section>
  )
}

function StepRow({ step }: { step: ResearchStep }) {
  return (
    <div className="grid grid-cols-[7rem_minmax(0,1fr)_5rem] items-start gap-3 border-b border-border/50 py-2 text-sm last:border-b-0">
      <div className="space-y-1">
        <Badge variant={statusBadge(step.status)}>{step.status}</Badge>
        <p className="text-xs text-muted-foreground">{step.step_type}</p>
      </div>
      <div className="min-w-0 space-y-1">
        <p className="truncate font-medium">{step.title || step.query || step.url || step.step_type}</p>
        {step.rationale ? (
          <p className="line-clamp-2 text-xs text-muted-foreground">{step.rationale}</p>
        ) : null}
        {step.error ? (
          <p className="line-clamp-2 text-xs text-destructive">{step.error}</p>
        ) : null}
      </div>
      <p className="text-right text-xs text-muted-foreground">{step.duration_ms} ms</p>
    </div>
  )
}

function EvidenceRow({ evidence }: { evidence: ResearchEvidence }) {
  const providerSource = textValue(evidence.metadata.provider_source)
  const providerRaw = evidence.metadata.provider_raw
  return (
    <article className="rounded-lg border border-border/70 bg-background p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge variant={qualityBadge(evidence.quality)}>{evidence.quality}</Badge>
        <Badge variant="outline">{evidence.source_type}</Badge>
        {providerSource ? <Badge variant="secondary">{providerSource}</Badge> : null}
        <span className="ml-auto text-xs text-muted-foreground">relevance {evidence.relevance}</span>
      </div>
      <p className="font-medium leading-relaxed">{evidence.claim}</p>
      {evidence.excerpt ? (
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{evidence.excerpt}</p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{evidence.source_title || "Untitled source"}</span>
        {evidence.source_url ? (
          <a
            href={evidence.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            <ExternalLink className="size-3" />
            source
          </a>
        ) : null}
      </div>
      {providerRaw !== undefined ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            Provider raw
          </summary>
          <div className="mt-2">
            <JsonPreview value={providerRaw} />
          </div>
        </details>
      ) : null}
    </article>
  )
}

export function ResearchView({ userId }: ResearchViewProps) {
  const [filter, setFilter] = useState<ResearchRunStatus | "">("")
  const [runs, setRuns] = useState<ResearchRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ResearchStateResult | null>(null)
  const [isLoadingRuns, setIsLoadingRuns] = useState(false)
  const [isLoadingDetail, setIsLoadingDetail] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selectedRun = useMemo(
    () => runs.find((run) => run.id === selectedRunId) ?? null,
    [runs, selectedRunId],
  )
  const conclusion = finalConclusion(detail)
  const admission = admissionSummary(detail)

  const loadRuns = useCallback(async () => {
    if (!userId) {
      setRuns([])
      setSelectedRunId(null)
      setDetail(null)
      return
    }
    setIsLoadingRuns(true)
    setError(null)
    try {
      const result = await listResearchRuns({
        userId,
        status: filter,
        limit: 50,
      })
      setRuns(result.runs)
      setSelectedRunId((current) => {
        if (current && result.runs.some((run) => run.id === current)) {
          return current
        }
        return result.runs[0]?.id ?? null
      })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load research runs")
    } finally {
      setIsLoadingRuns(false)
    }
  }, [filter, userId])

  const loadDetail = useCallback(async (runId: string | null) => {
    if (!userId || !runId) {
      setDetail(null)
      return
    }
    setIsLoadingDetail(true)
    setError(null)
    try {
      const result = await getResearchState({
        userId,
        runId,
        limitSteps: 100,
        limitEvidence: 100,
      })
      setDetail(result)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to load research state")
      setDetail(null)
    } finally {
      setIsLoadingDetail(false)
    }
  }, [userId])

  useEffect(() => {
    void loadRuns()
  }, [loadRuns])

  useEffect(() => {
    void loadDetail(selectedRunId)
  }, [loadDetail, selectedRunId])

  const refreshAll = useCallback(async () => {
    await loadRuns()
    await loadDetail(selectedRunId)
  }, [loadDetail, loadRuns, selectedRunId])

  const cancelSelected = useCallback(async () => {
    if (!userId || !selectedRunId || selectedRun?.status !== "active") {
      return
    }
    if (!window.confirm("Cancel this research run?")) {
      return
    }
    setIsCancelling(true)
    setError(null)
    try {
      const result = await cancelResearchRun({
        userId,
        runId: selectedRunId,
      })
      setDetail(result)
      await loadRuns()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to cancel research run")
    } finally {
      setIsCancelling(false)
    }
  }, [loadRuns, selectedRun?.status, selectedRunId, userId])

  return (
    <section className="grid h-full min-h-0 min-w-0 grid-cols-1 overflow-hidden border-x border-border/50 bg-background lg:grid-cols-[20rem_minmax(0,1fr)]">
      <aside className="min-h-0 border-b border-border/70 bg-muted/20 lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2 border-b border-border/70 p-3">
          <SearchCheck className="size-5 text-primary" />
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">Research</h2>
            <p className="text-xs text-muted-foreground">{runs.length} runs</p>
          </div>
          <Button
            type="button"
            size="icon-xs"
            variant="ghost"
            className="ml-auto"
            onClick={() => void refreshAll()}
            disabled={isLoadingRuns || isLoadingDetail}
            title="Refresh"
            aria-label="Refresh research"
          >
            <RefreshCw className={cn("size-4", (isLoadingRuns || isLoadingDetail) && "animate-spin")} />
          </Button>
        </div>

        <div className="flex flex-wrap gap-1 border-b border-border/70 p-2">
          {FILTERS.map((item) => (
            <Button
              key={item.label}
              type="button"
              size="xs"
              variant={filter === item.value ? "default" : "ghost"}
              onClick={() => setFilter(item.value)}
            >
              {item.label}
            </Button>
          ))}
        </div>

        <ScrollArea className="h-[18rem] lg:h-[calc(100vh-7rem)]">
          <div className="space-y-2 p-2">
            {isLoadingRuns && runs.length === 0 ? (
              <div className="flex items-center gap-2 p-3 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Loading
              </div>
            ) : null}
            {!isLoadingRuns && runs.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border/70 p-4 text-sm text-muted-foreground">
                No research runs.
              </p>
            ) : null}
            {runs.map((run) => {
              const isSelected = run.id === selectedRunId
              return (
                <button
                  key={run.id ?? run.objective}
                  type="button"
                  className={cn(
                    "w-full rounded-lg border p-3 text-left transition hover:border-primary/40 hover:bg-background",
                    isSelected
                      ? "border-primary/50 bg-background shadow-sm"
                      : "border-border/70 bg-background/70",
                  )}
                  onClick={() => setSelectedRunId(run.id)}
                >
                  <div className="mb-2 flex items-center gap-2">
                    <Badge variant={statusBadge(run.status)}>{run.status}</Badge>
                    <Badge variant="outline">{run.mode}</Badge>
                  </div>
                  <p className="line-clamp-2 text-sm font-medium leading-relaxed">
                    {run.objective}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {formatDate(run.updated_at ?? run.started_at)}
                  </p>
                </button>
              )
            })}
          </div>
        </ScrollArea>
      </aside>

      <main className="min-h-0 overflow-hidden">
        {error ? (
          <Alert variant="destructive" className="m-4">
            <AlertTitle>Research request failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {!detail && !isLoadingDetail ? (
          <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
            Select a research run.
          </div>
        ) : null}

        {isLoadingDetail ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading state
          </div>
        ) : null}

        {detail ? (
          <ScrollArea className="h-full">
            <div className="space-y-4 p-4">
              <section className="rounded-lg border border-border/70 bg-background p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start">
                  <div className="min-w-0 flex-1">
                    <div className="mb-2 flex flex-wrap gap-2">
                      <Badge variant={statusBadge(detail.run.status)}>{detail.run.status}</Badge>
                      <Badge variant="outline">{detail.run.mode}</Badge>
                      <Badge variant="secondary">{detail.provider_sources.join(", ") || "postgres"}</Badge>
                    </div>
                    <h1 className="text-xl font-semibold leading-snug">{detail.run.objective}</h1>
                    <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
                      <span>Started {formatDate(detail.run.started_at)}</span>
                      <span>Updated {formatDate(detail.run.updated_at)}</span>
                      {detail.run.finished_at ? <span>Finished {formatDate(detail.run.finished_at)}</span> : null}
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    onClick={() => void cancelSelected()}
                    disabled={detail.run.status !== "active" || isCancelling}
                  >
                    {isCancelling ? <Loader2 className="size-4 animate-spin" /> : <CircleStop className="size-4" />}
                    Cancel
                  </Button>
                </div>
              </section>

              <section className="grid gap-3 md:grid-cols-4">
                <div className="rounded-lg border border-border/70 bg-background p-3">
                  <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
                    <ShieldCheck className="size-4 text-primary" />
                    Verifier
                  </div>
                  <p className="text-2xl font-semibold">{admission.ready === null ? "--" : admission.ready ? "Ready" : "Blocked"}</p>
                </div>
                <div className="rounded-lg border border-border/70 bg-background p-3">
                  <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
                    <CheckCircle2 className="size-4 text-emerald-500" />
                    Admitted
                  </div>
                  <p className="text-2xl font-semibold">{admission.admitted}</p>
                </div>
                <div className="rounded-lg border border-border/70 bg-background p-3">
                  <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
                    <XCircle className="size-4 text-destructive" />
                    Rejected
                  </div>
                  <p className="text-2xl font-semibold">{admission.rejected}</p>
                </div>
                <div className="rounded-lg border border-border/70 bg-background p-3">
                  <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
                    <AlertTriangle className="size-4 text-amber-500" />
                    Uncertain
                  </div>
                  <p className="text-2xl font-semibold">{admission.uncertain}</p>
                </div>
              </section>

              {conclusion ? (
                <section className="rounded-lg border border-border/70 bg-background p-4">
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                    <FileText className="size-4 text-primary" />
                    Final answer
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{conclusion}</p>
                </section>
              ) : null}

              <section className="grid gap-3 xl:grid-cols-2">
                <ListBlock
                  title="Known facts"
                  items={detail.state.known_facts}
                  empty="No facts admitted yet."
                  icon={<CheckCircle2 className="size-4 text-emerald-500" />}
                />
                <ListBlock
                  title="Gaps"
                  items={detail.state.gaps}
                  empty="No open gaps."
                  icon={<AlertTriangle className="size-4 text-amber-500" />}
                />
                <ListBlock
                  title="Conflicts"
                  items={detail.state.conflicts}
                  empty="No conflicts recorded."
                  icon={<XCircle className="size-4 text-destructive" />}
                />
                <ListBlock
                  title="Next actions"
                  items={detail.state.next_actions}
                  empty="No pending actions."
                  icon={<Route className="size-4 text-primary" />}
                />
              </section>

              <section className="grid gap-3 xl:grid-cols-2">
                <ListBlock
                  title="Subquestions"
                  items={detail.state.subquestions}
                  empty="No subquestions recorded."
                  icon={<SearchCheck className="size-4 text-primary" />}
                />
                <ListBlock
                  title="Exhausted queries"
                  items={detail.state.exhausted_queries}
                  empty="No exhausted queries."
                  icon={<Route className="size-4 text-muted-foreground" />}
                />
              </section>

              <section className="space-y-3">
                <div className="flex items-center gap-2">
                  <FileText className="size-4 text-primary" />
                  <h2 className="text-sm font-semibold">Evidence</h2>
                  <Badge variant="secondary">{detail.evidence.length}</Badge>
                </div>
                {detail.evidence.length > 0 ? (
                  <div className="grid gap-3 xl:grid-cols-2">
                    {detail.evidence.map((item) => (
                      <EvidenceRow key={item.id ?? `${item.claim}-${item.source_url}`} evidence={item} />
                    ))}
                  </div>
                ) : (
                  <p className="rounded-lg border border-dashed border-border/70 p-4 text-sm text-muted-foreground">
                    No evidence recorded.
                  </p>
                )}
              </section>

              <Separator />

              <section>
                <div className="mb-2 flex items-center gap-2">
                  <Route className="size-4 text-primary" />
                  <h2 className="text-sm font-semibold">Steps</h2>
                  <Badge variant="secondary">{detail.steps.length}</Badge>
                </div>
                <div className="rounded-lg border border-border/70 bg-background px-3">
                  {detail.steps.length > 0 ? (
                    detail.steps.map((step) => (
                      <StepRow key={step.id ?? `${step.step_type}-${step.created_at}`} step={step} />
                    ))
                  ) : (
                    <p className="py-4 text-sm text-muted-foreground">No steps recorded.</p>
                  )}
                </div>
              </section>
            </div>
          </ScrollArea>
        ) : null}
      </main>
    </section>
  )
}
