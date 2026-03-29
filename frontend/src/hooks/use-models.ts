import { useState, useEffect, useCallback } from "react"
import { getAvailableModels } from "@/lib/api"
import type { ModelInfo } from "@/types"

/**
 * Hook to manage model selection per conversation.
 * 
 * @param threadId - The current conversation thread ID
 * @returns An object containing:
 *   - models: ModelInfo[] - All available models
 *   - thinkingModels: ModelInfo[] - Models marked as thinking models
 *   - nonThinkingModels: ModelInfo[] - Models not marked as thinking models
 *   - defaultModel: string | null - Default non-thinking model from backend
 *   - defaultThinkingModel: string | null - Default thinking model (first thinking model)
 *   - selectedModel: string | null - Currently selected non-thinking model name
 *   - selectedThinkingModel: string | null - Currently selected thinking model name
 *   - setSelectedModel: (name: string | null) => void - Update selected non-thinking model
 *   - setSelectedThinkingModel: (name: string | null) => void - Update selected thinking model
 *   - getEffectiveModel: (thinkingMode: boolean) => string | null - Get model for current mode
 *   - isLoading: boolean - Whether the models are being fetched
 *   - error: string | null - Error message if fetch failed
 */
export function useModels(threadId: string | null) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [defaultModel, setDefaultModel] = useState<string | null>(null)
  const [selectedModel, setSelectedModelState] = useState<string | null>(null)
  const [selectedThinkingModel, setSelectedThinkingModelState] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Get thinking models
  const thinkingModels = models.filter(m => m.is_thinking)
  
  // Get non-thinking models
  const nonThinkingModels = models.filter(m => !m.is_thinking)
  
  // Default thinking model: first thinking model available
  const defaultThinkingModel = thinkingModels.length > 0 ? thinkingModels[0].name : null

  // Fetch available models on mount
  useEffect(() => {
    let mounted = true
    
    async function fetchModels() {
      try {
        const result = await getAvailableModels()
        if (mounted) {
          setModels(result.models)
          setDefaultModel(result.default_model)
          setIsLoading(false)
          setError(null)
        }
      } catch (err) {
        console.error("Failed to fetch available models:", err)
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to fetch models")
          setIsLoading(false)
        }
      }
    }
    
    fetchModels()
    
    return () => {
      mounted = false
    }
  }, [])

  // Reset selection when threadId changes
  useEffect(() => {
    setSelectedModelState(defaultModel)
    setSelectedThinkingModelState(defaultThinkingModel)
  }, [threadId, defaultModel, defaultThinkingModel])

  // Update selected non-thinking model
  const setSelectedModel = useCallback((name: string | null) => {
    setSelectedModelState(name)
  }, [])

  // Update selected thinking model
  const setSelectedThinkingModel = useCallback((name: string | null) => {
    setSelectedThinkingModelState(name)
  }, [])

  // Get the effective model based on thinking mode
  const getEffectiveModel = useCallback((thinkingMode: boolean): string | null => {
    if (thinkingMode) {
      return selectedThinkingModel || defaultThinkingModel
    }
    return selectedModel || defaultModel
  }, [selectedModel, selectedThinkingModel, defaultModel, defaultThinkingModel])

  return {
    models,
    thinkingModels,
    nonThinkingModels,
    defaultModel,
    defaultThinkingModel,
    selectedModel,
    selectedThinkingModel,
    setSelectedModel,
    setSelectedThinkingModel,
    getEffectiveModel,
    isLoading,
    error,
  }
}