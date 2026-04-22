import { useMemo } from "react"
import { Brain, Eye, Sparkles } from "lucide-react"
import { useI18n } from "@/i18n"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import type { ModelInfo } from "@/types"

interface ModelSelectorProps {
  models: ModelInfo[]
  selectedModel: string | null
  onSelectModel: (modelId: string | null) => void
  disabled?: boolean
  onOpenConfig?: () => void // Callback to open model configuration dialog
}

/**
 * Get provider display name - uses raw provider value without mapping
 */
function getProviderDisplayName(provider: string): string {
  // Return provider as-is, only capitalize first letter for consistency
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

/**
 * Get short model name from full model_id
 * e.g., "dashscope/qwen3.5-27b" -> "qwen3.5-27b"
 */
function getShortModelName(modelId: string): string {
  const parts = modelId.split("/")
  return parts.length > 1 ? parts.slice(1).join("/") : modelId
}

/**
 * Model type icon component
 */
function ModelTypeIcon({ type, className }: { type: string; className?: string }) {
  if (type === "vlm") {
    return <Eye className={className} />
  }
  return <Brain className={className} />
}

/**
 * A dropdown selector for choosing a model.
 *
 * Shows all available active LLM and VLM models (not embedding models).
 * Models are grouped by provider with type icons and capability badges.
 */
export function ModelSelector({
  models,
  selectedModel,
  onSelectModel,
  disabled = false,
}: ModelSelectorProps) {
  const { t } = useI18n()

  // Group models by provider
  const groupedModels = useMemo(() => {
    // Filter to show only LLM and VLM models that are active
    const availableModels = models.filter(
      m => (m.model_type === "llm" || m.model_type === "vlm") && m.is_active
    )

    // Group by provider
    const groups: Record<string, ModelInfo[]> = {}
    availableModels.forEach(model => {
      if (!groups[model.provider]) {
        groups[model.provider] = []
      }
      groups[model.provider].push(model)
    })

    // Sort providers alphabetically and sort models within each group
    const sortedProviders = Object.keys(groups).sort()
    return sortedProviders.map(provider => ({
      provider,
      displayName: getProviderDisplayName(provider),
      models: groups[provider].sort((a, b) => getShortModelName(a.model_id).localeCompare(getShortModelName(b.model_id))),
    }))
  }, [models])

  // If no available models, don't render anything (dialog will be shown by parent)
  if (groupedModels.length === 0) {
    return null
  }

  // Get selected model info for display
  const selectedModelInfo = models.find(m => m.model_id === selectedModel)

  return (
    <Select
      value={selectedModel || ""}
      onValueChange={(value) => {
        onSelectModel(value || null)
      }}
      disabled={disabled}
    >
      <SelectTrigger
        size="sm"
        className="h-9 px-3 text-sm w-[180px] border-border/60 bg-background/80 backdrop-blur-sm hover:bg-accent/30 hover:border-primary/40 transition-all duration-200"
      >
        <SelectValue placeholder={
          <span className="flex items-center gap-2 text-muted-foreground">
            <Sparkles className="size-3.5" />
            {t("model.select")}
          </span>
        }>
          {selectedModelInfo && (
            <span className="flex items-center gap-2">
              <ModelTypeIcon
                type={selectedModelInfo.model_type}
                className="size-3.5 text-primary"
              />
              <span className="truncate">{getShortModelName(selectedModelInfo.model_id)}</span>
              {selectedModelInfo.thinking && (
                <Sparkles className="size-3 text-amber-500" />
              )}
            </span>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent
        position="popper"
        side="top"
        align="start"
        className="max-h-[320px] w-[220px] border-border/60 bg-popover/95 backdrop-blur-md"
      >
        {groupedModels.map(({ provider, displayName, models: providerModels }) => (
          <SelectGroup key={provider}>
            <SelectLabel className="px-2 py-1.5 text-xs font-semibold text-muted-foreground/80 uppercase tracking-wider">
              {displayName}
            </SelectLabel>
            {providerModels.map((model) => (
              <SelectItem
                key={model.model_id}
                value={model.model_id}
                className="py-2 px-2 cursor-pointer focus:bg-accent/50"
              >
                <span className="flex items-center gap-2 w-full">
                  <ModelTypeIcon
                    type={model.model_type}
                    className="size-3.5 text-muted-foreground shrink-0"
                  />
                  <span className="flex-1 truncate text-sm">
                    {getShortModelName(model.model_id)}
                  </span>
                  <span className="flex items-center gap-1 shrink-0">
                    {model.thinking && (
                      <span title={t("model.thinking")}>
                        <Sparkles className="size-3 text-amber-500" />
                      </span>
                    )}
                    {model.model_type === "vlm" && (
                      <Badge variant="secondary" className="text-[9px] px-1 py-0 h-4">
                        Vision
                      </Badge>
                    )}
                  </span>
                </span>
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  )
}
