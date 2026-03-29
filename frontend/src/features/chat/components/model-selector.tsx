import { useI18n } from "@/i18n"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { ModelInfo } from "@/types"

interface ModelSelectorProps {
  models: ModelInfo[]
  selectedModel: string | null
  onSelectModel: (name: string | null) => void
  disabled?: boolean
}

/**
 * A dropdown selector for choosing a model.
 * 
 * Shows a list of available models and allows the user to select one.
 * When a model is selected, it's passed to the parent component.
 * The dropdown pops up instead of down since it's at the bottom of the page.
 */
export function ModelSelector({
  models,
  selectedModel,
  onSelectModel,
  disabled = false,
}: ModelSelectorProps) {
  const { t } = useI18n()

  if (models.length === 0) {
    return null
  }

  return (
    <Select
      value={selectedModel || ""}
      onValueChange={(value) => {
        onSelectModel(value || null)
      }}
      disabled={disabled}
    >
      <SelectTrigger size="sm" className="h-7 px-2 text-xs w-[140px]">
        <SelectValue placeholder={t("model.select")} />
      </SelectTrigger>
      <SelectContent position="popper" side="top" align="start" className="max-h-[300px]">
        {models.map((model) => (
          <SelectItem key={model.name} value={model.name}>
            {model.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}