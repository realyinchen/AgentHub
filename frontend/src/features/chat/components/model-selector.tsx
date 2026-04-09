import { useI18n } from "@/i18n"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import type { ModelInfo } from "@/types"

interface ModelSelectorProps {
  models: ModelInfo[]
  selectedModel: string | null
  onSelectModel: (modelId: string | null) => void
  disabled?: boolean
}

/**
 * A dropdown selector for choosing a model.
 * 
 * Shows all available active LLM and VLM models (not embedding models).
 * Each model shows its provider name for disambiguation.
 */
export function ModelSelector({
  models,
  selectedModel,
  onSelectModel,
  disabled = false,
}: ModelSelectorProps) {
  const { t } = useI18n()

  // Filter to show only LLM and VLM models that are active, then sort alphabetically by model_name
  const availableModels = models
    .filter(m =>
      (m.model_type === "llm" || m.model_type === "vlm") && m.is_active
    )
    .sort((a, b) => a.model_name.localeCompare(b.model_name))

  if (availableModels.length === 0) {
    return (
      <Button
        size="sm"
        variant="outline"
        className="h-7 px-2 text-xs"
        disabled
      >
        {t("model.select")}
      </Button>
    )
  }

  // Get display name - just show model_name (e.g., "glm5")
  const getDisplayName = (model: ModelInfo): string => {
    return model.model_name
  }

  return (
    <Select
      value={selectedModel || ""}
      onValueChange={(value) => {
        onSelectModel(value || null)
      }}
      disabled={disabled}
    >
      <SelectTrigger size="sm" className="h-7 px-2 text-xs w-full">
        <SelectValue placeholder={t("model.select")} />
      </SelectTrigger>
      <SelectContent position="popper" side="top" align="start" className="max-h-[300px]">
        {availableModels.map((model) => (
          <SelectItem key={model.model_id} value={model.model_id}>
            {getDisplayName(model)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}