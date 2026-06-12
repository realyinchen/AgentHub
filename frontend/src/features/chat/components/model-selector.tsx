import { useMemo } from "react"
import { Brain, Eye } from "lucide-react"
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

function getModelKey(model: ModelInfo): string {
  return model.model_uuid || model.id
}

function getModelProvider(model: ModelInfo): string {
  return model.provider_key || model.provider
}

function getModelConnectionName(model: ModelInfo): string {
  return model.connection_name || getProviderDisplayName(getModelProvider(model))
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
 * Models are grouped by provider with type icons and thinking capability indicators.
 * 
 * Display format: provider/model_id with Brain icon (amber if thinking enabled, gray if not)
 */
export function ModelSelector({
  models,
  selectedModel,
  onSelectModel,
  disabled = false,
}: ModelSelectorProps) {
  const { t } = useI18n()

  // Group models by provider + connection
  const groupedModels = useMemo(() => {
    // Filter to show only LLM and VLM models that are active
    const availableModels = models.filter(
      m => (m.model_type === "llm" || m.model_type === "vlm") && m.is_active
    )

    // Group by provider/connection so duplicate provider model IDs do not collide visually.
    const groups: Record<string, ModelInfo[]> = {}
    availableModels.forEach(model => {
      const groupKey = `${getModelProvider(model)}:${model.connection_id || "legacy"}`
      if (!groups[groupKey]) {
        groups[groupKey] = []
      }
      groups[groupKey].push(model)
    })

    const sortedGroups = Object.keys(groups).sort()
    return sortedGroups.map(groupKey => ({
      groupKey,
      displayName: getModelConnectionName(groups[groupKey][0]),
      models: groups[groupKey].sort((a, b) => getShortModelName(a.provider_model_id || a.model_id).localeCompare(getShortModelName(b.provider_model_id || b.model_id))),
    }))
  }, [models])

  // If no available models, don't render anything (dialog will be shown by parent)
  if (groupedModels.length === 0) {
    return null
  }

  // Get selected model info for display
  const selectedModelInfo = models.find(m => getModelKey(m) === selectedModel)

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
        className="h-9 px-3 text-sm w-[200px] border-border/60 bg-background/80 backdrop-blur-sm hover:bg-accent/30 hover:border-primary/40 transition-all duration-200"
      >
        <SelectValue placeholder={
          <span className="flex items-center gap-2 text-muted-foreground">
            <Brain className="size-3.5" />
            {t("model.select")}
          </span>
        }>
          {selectedModelInfo && (
            <span className="flex items-center gap-2">
              {/* Brain icon: amber if thinking enabled, gray if not */}
              <Brain
                className={`size-3.5 ${selectedModelInfo.thinking ? 'text-amber-500' : 'text-muted-foreground'}`}
              />
              {/* Display as provider/model_id */}
              <span className="truncate text-xs">
                {getModelConnectionName(selectedModelInfo)}/{getShortModelName(selectedModelInfo.provider_model_id || selectedModelInfo.model_id)}
              </span>
            </span>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent
        position="popper"
        side="top"
        align="start"
        className="max-h-[320px] w-[240px] border-border/60 bg-popover/95 backdrop-blur-md"
      >
        {groupedModels.map(({ groupKey, displayName, models: providerModels }) => (
          <SelectGroup key={groupKey}>
            <SelectLabel className="px-2 py-1.5 text-xs font-semibold text-muted-foreground/80 uppercase tracking-wider">
              {displayName}
            </SelectLabel>
            {providerModels.map((model) => (
              <SelectItem
                key={getModelKey(model)}
                value={getModelKey(model)}
                className="py-2 px-2 cursor-pointer focus:bg-accent/50"
              >
                <span className="flex items-center gap-2 w-full">
                  {/* Model type icon: amber if thinking enabled, gray if not */}
                  <ModelTypeIcon
                    type={model.model_type}
                    className={`size-3.5 shrink-0 ${model.thinking ? 'text-blue-500' : 'text-muted-foreground'}`}
                  />
                  {/* Short model name */}
                  <span className="flex-1 truncate text-sm">
                    {getShortModelName(model.provider_model_id || model.model_id)}
                  </span>
                  {/* VLM badge */}
                  {model.model_type === "vlm" && (
                    <Badge variant="secondary" className="text-[9px] px-1 py-0 h-4 shrink-0">
                      Vision
                    </Badge>
                  )}
                </span>
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  )
}
