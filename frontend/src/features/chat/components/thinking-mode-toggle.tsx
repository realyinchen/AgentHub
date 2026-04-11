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
  modelSupportsThinking: boolean  // Whether the current model supports thinking mode
  onToggle: () => void
}

/**
 * A toggle button for enabling/disabling thinking mode.
 * 
 * Displays a brain icon that is colored when thinking mode is enabled,
 * and grayscale when disabled.
 * 
 * When the current model doesn't support thinking mode, the button is disabled
 * and shows a tooltip explaining why.
 */
export function ThinkingModeToggle({
  enabled,
  modelSupportsThinking,
  onToggle,
}: ThinkingModeToggleProps) {
  const { t } = useI18n()

  // Determine tooltip text based on model support and current state
  const tooltipText = !modelSupportsThinking
    ? t("thinking.notSupported")
    : enabled
      ? t("thinking.enabled")
      : t("thinking.clickToEnable")

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <InputGroupButton
            type="button"
            variant="ghost"
            size="icon-sm"
            className="rounded-full scale-150 origin-center"
            onClick={modelSupportsThinking ? onToggle : undefined}
            disabled={!modelSupportsThinking}
          >
            <Brain
              className={`size-4 transition-colors ${!modelSupportsThinking
                  ? "text-muted-foreground/50"
                  : enabled
                    ? "text-purple-500 dark:text-purple-400"
                    : "text-muted-foreground"
                }`}
            />
            <span className="sr-only">
              {tooltipText}
            </span>
          </InputGroupButton>
        </TooltipTrigger>
        <TooltipContent>
          <p className={!modelSupportsThinking ? "text-muted-foreground" : ""}>
            {tooltipText}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}