import { useCallback, useEffect, useMemo, useState } from "react"
import { KeyRound, RefreshCw, Save } from "lucide-react"

import type {
  AppProviderCapability,
  AppProviderConfig,
  AppProviderScope,
} from "@/types"
import {
  checkAppProviderHealth,
  getAppProviderConfigs,
  updateAppProviderConfig,
} from "@/lib/api"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

type AppProviderConfigDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

const CAPABILITIES: AppProviderCapability[] = [
  "memory_recall",
  "semantic_search",
  "research_observation",
  "web_search",
  "source_visit",
]

const SCOPES: AppProviderScope[] = ["global", "workspace", "user"]

function formatJson(value: Record<string, unknown>): string {
  return JSON.stringify(value ?? {}, null, 2)
}

function parseSettings(text: string): Record<string, unknown> {
  const trimmed = text.trim()
  if (!trimmed) return {}
  const parsed = JSON.parse(trimmed) as unknown
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("settings must be a JSON object")
  }
  return parsed as Record<string, unknown>
}

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "ok") return "default"
  if (status === "disabled" || status === "unknown") return "secondary"
  if (status === "missing_credentials" || status === "failed" || status === "timeout") {
    return "destructive"
  }
  return "outline"
}

function formatCheckedAt(value: string | null): string {
  if (!value) return "Never"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

export function AppProviderConfigDialog({
  open,
  onOpenChange,
}: AppProviderConfigDialogProps) {
  const [providers, setProviders] = useState<AppProviderConfig[]>([])
  const [selectedKey, setSelectedKey] = useState<string>("")
  const [enabled, setEnabled] = useState(false)
  const [scope, setScope] = useState<AppProviderScope>("global")
  const [apiKey, setApiKey] = useState("")
  const [settingsText, setSettingsText] = useState("{}")
  const [selectedCapabilities, setSelectedCapabilities] = useState<
    AppProviderCapability[]
  >([])
  const [isLoading, setIsLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState("")

  const selected = useMemo(
    () => providers.find((provider) => provider.provider_key === selectedKey) ?? null,
    [providers, selectedKey],
  )

  const loadProviders = useCallback(async () => {
    setIsLoading(true)
    setError("")
    try {
      const result = await getAppProviderConfigs()
      setProviders(result.providers)
      const firstKey = result.providers[0]?.provider_key ?? ""
      setSelectedKey((current) =>
        current && result.providers.some((provider) => provider.provider_key === current)
          ? current
          : firstKey,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) void loadProviders()
  }, [open, loadProviders])

  useEffect(() => {
    if (!selected) return
    setEnabled(selected.enabled)
    setScope(selected.scope)
    setSettingsText(formatJson(selected.settings))
    setSelectedCapabilities(selected.capabilities)
    setApiKey("")
  }, [selected])

  const toggleCapability = (capability: AppProviderCapability) => {
    setSelectedCapabilities((current) =>
      current.includes(capability)
        ? current.filter((item) => item !== capability)
        : [...current, capability],
    )
  }

  const saveSelected = async () => {
    if (!selected) return
    setIsSaving(true)
    setError("")
    try {
      const updated = await updateAppProviderConfig(selected.provider_key, {
        enabled,
        scope,
        capabilities: selectedCapabilities,
        settings: parseSettings(settingsText),
        api_key: apiKey.trim() || null,
      })
      setProviders((current) =>
        current.map((provider) =>
          provider.provider_key === updated.provider_key ? updated : provider,
        ),
      )
      setApiKey("")
      if (updated.provider_type === "web_search" && updated.enabled) {
        const checked = await checkAppProviderHealth(updated.provider_key)
        setProviders((current) =>
          current.map((provider) =>
            provider.provider_key === checked.provider_key ? checked : provider,
          ),
        )
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setIsSaving(false)
    }
  }

  const refreshHealth = async () => {
    if (!selected) return
    setIsSaving(true)
    setError("")
    try {
      const updated = await checkAppProviderHealth(selected.provider_key)
      setProviders((current) =>
        current.map((provider) =>
          provider.provider_key === updated.provider_key ? updated : provider,
        ),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl max-h-[86vh] overflow-hidden">
        <DialogHeader>
          <DialogTitle>App Providers</DialogTitle>
          <DialogDescription>
            Server-side providers for memory, research observations, and web search.
            Secrets are stored encrypted and never returned to the browser.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="grid min-h-[520px] grid-cols-[220px_1fr] overflow-hidden rounded-md border border-border">
          <div className="border-r border-border bg-muted/30 p-2">
            {isLoading ? (
              <div className="p-3 text-sm text-muted-foreground">Loading...</div>
            ) : (
              <div className="space-y-1">
                {providers.map((provider) => (
                  <button
                    key={provider.provider_key}
                    type="button"
                    onClick={() => setSelectedKey(provider.provider_key)}
                    className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                      provider.provider_key === selectedKey
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-background"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{provider.display_name || provider.provider_key}</span>
                      <Badge variant={provider.enabled ? "default" : "secondary"}>
                        {provider.enabled ? "on" : "off"}
                      </Badge>
                    </div>
                    <div className="mt-1 truncate text-xs opacity-75">
                      {provider.provider_type}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="min-w-0 overflow-y-auto p-4">
            {selected ? (
              <div className="space-y-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="text-lg font-semibold">
                      {selected.display_name || selected.provider_key}
                    </h3>
                    <div className="mt-1 flex flex-wrap gap-2">
                      <Badge variant="outline">{selected.provider_type}</Badge>
                      <Badge variant="outline">{selected.scope}</Badge>
                      <Badge variant={statusVariant(selected.health.status)}>
                        {selected.health.status}
                      </Badge>
                      <Badge variant="secondary">{selected.credential_status}</Badge>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void refreshHealth()}
                      disabled={isSaving}
                    >
                      <RefreshCw className={`mr-2 size-4 ${isSaving ? "animate-spin" : ""}`} />
                      Test connection
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => void saveSelected()}
                      disabled={isSaving}
                    >
                      <Save className="mr-2 size-4" />
                      Save
                    </Button>
                  </div>
                </div>

                <div className="rounded-md border border-border px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">Health</span>
                    <Badge variant={statusVariant(selected.health.status)}>
                      {selected.health.status}
                    </Badge>
                    <span className="text-muted-foreground">
                      Last tested: {formatCheckedAt(selected.health.checked_at)}
                    </span>
                    {selected.health.duration_ms > 0 && (
                      <span className="text-muted-foreground">
                        {selected.health.duration_ms} ms
                      </span>
                    )}
                  </div>
                  {selected.provider_type === "web_search" && (
                    <div className="mt-2 text-xs text-muted-foreground">
                      Save stores the encrypted key, then Test connection runs a live
                      provider query from the backend. AnySearch can run anonymously;
                      only an ok result means this provider is usable.
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Enabled</label>
                    <div className="flex h-10 items-center gap-3 rounded-md border border-border px-3">
                      <Switch checked={enabled} onCheckedChange={setEnabled} />
                      <span className="text-sm text-muted-foreground">
                        {enabled ? "Enabled" : "Disabled"}
                      </span>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Scope</label>
                    <Select
                      value={scope}
                      onValueChange={(value) => setScope(value as AppProviderScope)}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {SCOPES.map((item) => (
                          <SelectItem key={item} value={item}>
                            {item}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium">API Key</label>
                  <div className="flex items-center gap-2">
                    <KeyRound className="size-4 text-muted-foreground" />
                    <Input
                      type="password"
                      value={apiKey}
                      onChange={(event) => setApiKey(event.target.value)}
                      placeholder={
                        selected.credential_status === "configured"
                          ? "Configured. Paste a new key to replace it."
                          : "Paste API key"
                      }
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium">Capabilities</label>
                  <div className="flex flex-wrap gap-2">
                    {CAPABILITIES.map((capability) => {
                      const active = selectedCapabilities.includes(capability)
                      return (
                        <Button
                          key={capability}
                          type="button"
                          variant={active ? "default" : "outline"}
                          size="sm"
                          onClick={() => toggleCapability(capability)}
                        >
                          {capability}
                        </Button>
                      )
                    })}
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium">Settings JSON</label>
                  <Textarea
                    value={settingsText}
                    onChange={(event) => setSettingsText(event.target.value)}
                    className="min-h-44 font-mono text-xs"
                    spellCheck={false}
                  />
                </div>

                {selected.health.error && (
                  <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                    {selected.health.error}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                No provider selected
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
