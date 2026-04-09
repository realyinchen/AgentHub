import { useState, useEffect, useCallback, useRef } from "react"
import { getAvailableModels } from "@/lib/api"
import type { ModelInfo } from "@/types"

/**
 * Hook to manage model selection per conversation.
 * 
 * @param threadId - The current conversation thread ID
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
export function useModels(threadId: string | null) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [defaultModel, setDefaultModel] = useState<string | null>(null)
  const [selectedModel, setSelectedModelState] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Track if component is mounted to prevent state updates after unmount
  const mountedRef = useRef(true)

  // Unified fetch function with mounted check
  const fetchModels = useCallback(async () => {
    setIsLoading(true)
    try {
      const result = await getAvailableModels()
      if (mountedRef.current) {
        setModels(result.models)
        setDefaultModel(result.default_llm)
        setError(null)
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
  }, [])

  // Fetch models on mount
  useEffect(() => {
    mountedRef.current = true
    fetchModels()

    return () => {
      mountedRef.current = false
    }
  }, [fetchModels])

  // Reset selection when threadId changes, but use default model if available
  useEffect(() => {
    // Set to default model if available, otherwise null
    setSelectedModelState(defaultModel)
  }, [threadId, defaultModel])

  // Update selected model
  const setSelectedModel = useCallback((modelId: string | null) => {
    setSelectedModelState(modelId)
  }, [])

  // Get the selected model's info
  const getSelectedModelInfo = useCallback((): ModelInfo | undefined => {
    const modelId = selectedModel || defaultModel
    return models.find(m => m.model_id === modelId)
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