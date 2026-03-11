import { Brain } from "lucide-react"
import { InputGroupButton } from "@/components/ui/input-group"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useI18n } from "@/i18n"

interface ThinkingModeToggleProps {
  enabled: boolean
  available: boolean
  loading: boolean
  onToggle: () => void
}

/**
 * A toggle button for enabling/disabling thinking mode.
 * 
 * Displays a brain icon that is colored when thinking mode is enabled,
 * and grayscale when disabled. Only shows when thinking mode is available.
 */
export function ThinkingModeToggle({
  enabled,
  available,
  loading,
  onToggle,
}: ThinkingModeToggleProps) {
  const { t } = useI18n()
  
  // Don't render if thinking mode is not available or still loading
  if (loading || !available) {
    return null
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <InputGroupButton
            type="button"
            variant="ghost"
            size="icon-sm"
            className="rounded-full scale-150 origin-center"
            onClick={onToggle}
          >
            <Brain
              className={`size-4 transition-colors ${
                enabled
                  ? "text-purple-500 dark:text-purple-400"
                  : "text-muted-foreground"
              }`}
            />
            <span className="sr-only">
              {enabled ? t("thinking.disabled") : t("thinking.enabled")}
            </span>
          </InputGroupButton>
        </TooltipTrigger>
        <TooltipContent>
          <p>
            {enabled
              ? t("thinking.enabled")
              : t("thinking.disabled")}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}