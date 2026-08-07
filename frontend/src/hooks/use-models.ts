import { useState, useEffect, useCallback, useRef } from "react"
import { getAvailableModels } from "@/lib/api"
import type { ModelInfo } from "@/types"

function getModelKey(model: ModelInfo): string {
  return model.model_uuid || model.id
}

function storageKey(userId: string | null): string {
  return `agent-hub:selected-model:${userId || "guest"}`
}

/**
 * Hook to manage model selection as a persistent per-user preference.
 *
 * @param threadId - The current conversation thread ID
 * @param isLoggedIn - Whether the user is logged in (API calls only made when logged in)
 * @param userId - The effective user id, used to scope the persisted preference
 * @returns An object containing:
 *   - models: ModelInfo[] - All available models
 *   - selectedModel: string | null - Currently selected model ID
 *   - setSelectedModel: (name: string | null) => void - Update selected model
 *   - getSelectedModelInfo: () => ModelInfo | undefined - Get the selected model's info
 *   - defaultModel: string | null - Default LLM model from backend
 *   - refreshModels: () => Promise<void> - Refresh models from backend
 *   - isLoading: boolean - Whether the models are being fetched
 *   - error: string | null - Error message if fetch failed
 */
export function useModels(
  _threadId: string | null,
  isLoggedIn: boolean,
  userId: string | null,
) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [defaultModel, setDefaultModel] = useState<string | null>(null)
  const [selectedModel, setSelectedModelState] = useState<string | null>(() => {
    if (typeof window === "undefined") return null
    return window.localStorage.getItem(storageKey(userId))
  })
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Track if component is mounted to prevent state updates after unmount
  const mountedRef = useRef(true)
  // Track if we've already fetched models after login
  const hasFetchedRef = useRef(false)

  // Unified fetch function with mounted check
  const fetchModels = useCallback(async () => {
    setIsLoading(true)
    try {
      const result = await getAvailableModels()
      if (mountedRef.current) {
        const availableKeys = new Set(result.models.map(getModelKey))
        setModels(result.models)
        setDefaultModel(result.default_llm)
        setSelectedModelState(current => {
          if (current && !availableKeys.has(current)) {
            const fallback = result.default_llm
            if (typeof window !== "undefined") {
              if (fallback) {
                window.localStorage.setItem(storageKey(userId), fallback)
              } else {
                window.localStorage.removeItem(storageKey(userId))
              }
            }
            return fallback
          }
          return current
        })
        setError(null)
        hasFetchedRef.current = true
      }
    } catch (err) {
      console.error("Failed to fetch available models:", err)
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : "Failed to fetch models")
      }
    } finally {
      if (mountedRef.current) {
        setIsLoading(false)
      }
    }
  }, [userId])

  // Fetch models only after user logs in
  useEffect(() => {
    mountedRef.current = true
    
    // Only fetch models when user is logged in
    if (isLoggedIn && !hasFetchedRef.current) {
      fetchModels()
    }

    return () => {
      mountedRef.current = false
    }
  }, [fetchModels, isLoggedIn])

  // Load the persisted preference when the active user changes.
  useEffect(() => {
    if (typeof window === "undefined") return
    const stored = window.localStorage.getItem(storageKey(userId))
    setSelectedModelState(stored)
  }, [userId])

  // Update selected model
  const setSelectedModel = useCallback((modelId: string | null) => {
    setSelectedModelState(modelId)
    if (typeof window !== "undefined") {
      if (modelId) {
        window.localStorage.setItem(storageKey(userId), modelId)
      } else {
        window.localStorage.removeItem(storageKey(userId))
      }
    }
  }, [userId])

  // Get the selected model's info
  const getSelectedModelInfo = useCallback((): ModelInfo | undefined => {
    const modelId = selectedModel || defaultModel
    return models.find(m => getModelKey(m) === modelId)
  }, [selectedModel, defaultModel, models])

  // Get effective model ID (selected or default)
  const getEffectiveModel = useCallback((): string | null => {
    return selectedModel || defaultModel
  }, [selectedModel, defaultModel])

  return {
    models,
    selectedModel,
    setSelectedModel,
    getSelectedModelInfo,
    getEffectiveModel,
    defaultModel,
    refreshModels: fetchModels,
    isLoading,
    error,
  }
}
