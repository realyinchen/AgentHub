"use client"

import { CopyIcon, RefreshCcwIcon, ThumbsDownIcon, ThumbsUpIcon } from "lucide-react"
import type { ComponentProps } from "react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { Message, MessageContent } from "~/components/ai/message"
import { useI18n } from "@/i18n"

export type ActionsProps = ComponentProps<"div">

export const Actions = ({ className, children, ...props }: ActionsProps) => (
  <div className={cn("flex items-center gap-1", className)} {...props}>
    {children}
  </div>
)

export type ActionProps = ComponentProps<typeof Button> & {
  tooltip?: string
  label?: string
}

export const Action = ({
  tooltip,
  children,
  label,
  className,
  variant = "ghost",
  size = "sm",
  ...props
}: ActionProps) => {
  const button = (
    <Button
      className={cn("size-9 p-1.5 text-muted-foreground hover:text-foreground", className)}
      size={size}
      type="button"
      variant={variant}
      {...props}
    >
      {children}
      <span className="sr-only">{label || tooltip}</span>
    </Button>
  )

  if (tooltip) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>{button}</TooltipTrigger>
          <TooltipContent>
            <p>{tooltip}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    )
  }

  return button
}

/** Demo component for preview */
export default function ActionsDemo() {
  const { t } = useI18n()

  return (
    <div className="flex w-full flex-col gap-4 p-6">
      <Message from="assistant">
        <MessageContent>
          {t("actions.demo.message")}
        </MessageContent>

        <Actions>
          <Action onClick={() => console.log(t("actions.demo.copiedLog"))} tooltip={t("actions.demo.copyTooltip")}>
            <CopyIcon className="size-4" />
          </Action>
          <Action
            onClick={() => console.log(t("actions.demo.regeneratingLog"))}
            tooltip={t("actions.demo.regenerateTooltip")}
          >
            <RefreshCcwIcon className="size-4" />
          </Action>
          <Action onClick={() => console.log(t("actions.demo.thumbsUpLog"))} tooltip={t("actions.demo.goodTooltip")}>
            <ThumbsUpIcon className="size-4" />
          </Action>
          <Action onClick={() => console.log(t("actions.demo.thumbsDownLog"))} tooltip={t("actions.demo.badTooltip")}>
            <ThumbsDownIcon className="size-4" />
          </Action>
        </Actions>
      </Message>
    </div>
  )
}
