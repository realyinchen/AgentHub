import { useState, useEffect, useCallback } from "react"

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
 */
export function useThinkingMode(threadId: string | null) {
  const [thinkingMode, setThinkingModeState] = useState(false)

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
  }
}