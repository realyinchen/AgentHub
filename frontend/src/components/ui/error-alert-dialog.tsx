"use client"

import { AlertTriangle } from "lucide-react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"

export type ErrorAlertState = {
  open: boolean
  message: string
}

export function ErrorAlertDialog({
  state,
  onOpenChange,
}: {
  state: ErrorAlertState
  onOpenChange: (open: boolean) => void
}) {
  return (
    <AlertDialog open={state.open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader className="items-center text-center">
          <div className="flex items-center justify-center gap-3 mb-2">
            <div className="flex items-center justify-center size-10 rounded-full bg-yellow-100 dark:bg-yellow-900/30">
              <AlertTriangle className="size-6 text-yellow-600 dark:text-yellow-500" />
            </div>
            <AlertDialogTitle className="text-xl font-bold text-left">
              {state.message}
            </AlertDialogTitle>
          </div>
        </AlertDialogHeader>
        <AlertDialogFooter className="justify-center">
          <AlertDialogAction>确定</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

import { useState, useCallback } from "react"

export function useErrorAlert() {
  const [state, setState] = useState<ErrorAlertState>({ open: false, message: "" })

  const showError = useCallback((message: string) => {
    setState({ open: true, message })
  }, [])

  const hideError = useCallback(() => {
    setState(prev => ({ ...prev, open: false }))
  }, [])

  const setOpen = useCallback((open: boolean) => {
    setState(prev => ({ ...prev, open }))
  }, [])

  return {
    state,
    showError,
    hideError,
    setOpen,
  }
}