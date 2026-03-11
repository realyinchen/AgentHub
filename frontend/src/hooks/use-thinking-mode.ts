import { useState, useEffect, useCallback } from "react"
import { getThinkingModeStatus } from "@/lib/api"

const STORAGE_KEY_PREFIX = "thinking_mode_"

/**
 * Hook to manage thinking mode state per conversation.
 * 
 * Thinking mode state is persisted in localStorage per thread_id,
 * so it survives page refreshes and navigation.
 * 
 * @param threadId - The current conversation thread ID
 * @returns An object containing:
 *   - thinkingMode: boolean - Current thinking mode state
 *   - setThinkingMode: (value: boolean) => void - Update thinking mode
 *   - toggleThinkingMode: () => void - Toggle thinking mode
 *   - isAvailable: boolean - Whether thinking mode is available (THINKING_LLM_NAME configured)
 *   - isLoading: boolean - Whether the availability check is in progress
 */
export function useThinkingMode(threadId: string | null) {
  const [thinkingMode, setThinkingModeState] = useState(false)
  const [isAvailable, setIsAvailable] = useState(false)
  const [isLoading, setIsLoading] = useState(true)

  // Check if thinking mode is available on mount
  useEffect(() => {
    let mounted = true
    
    async function checkAvailability() {
      try {
        const result = await getThinkingModeStatus()
        if (mounted) {
          setIsAvailable(result.available)
          setIsLoading(false)
        }
      } catch (error) {
        console.error("Failed to check thinking mode availability:", error)
        if (mounted) {
          setIsAvailable(false)
          setIsLoading(false)
        }
      }
    }
    
    checkAvailability()
    
    return () => {
      mounted = false
    }
  }, [])

  // Load thinking mode state from localStorage when threadId changes
  useEffect(() => {
    if (!threadId) {
      setThinkingModeState(false)
      return
    }
    
    const storageKey = `${STORAGE_KEY_PREFIX}${threadId}`
    const stored = localStorage.getItem(storageKey)
    if (stored !== null) {
      setThinkingModeState(stored === "true")
    } else {
      setThinkingModeState(false)
    }
  }, [threadId])

  // Update thinking mode and persist to localStorage
  const setThinkingMode = useCallback((value: boolean) => {
    setThinkingModeState(value)
    
    if (threadId) {
      const storageKey = `${STORAGE_KEY_PREFIX}${threadId}`
      localStorage.setItem(storageKey, String(value))
    }
  }, [threadId])

  // Toggle thinking mode - use functional update to avoid stale closure
  const toggleThinkingMode = useCallback(() => {
    setThinkingModeState((prev) => {
      const newValue = !prev
      if (threadId) {
        const storageKey = `${STORAGE_KEY_PREFIX}${threadId}`
        localStorage.setItem(storageKey, String(newValue))
      }
      return newValue
    })
  }, [threadId])

  return {
    thinkingMode,
    setThinkingMode,
    toggleThinkingMode,
    isAvailable,
    isLoading,
  }
}