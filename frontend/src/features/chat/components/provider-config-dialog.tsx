import { useState, useEffect, useCallback } from "react"
import { Eye, EyeOff, Plus, Trash2, Settings2, HelpCircle } from "lucide-react"

import type { ModelInfo, ModelType, ModelCreate, ModelUpdate } from "@/types"
import { getAllModels, createModel, updateModel, deleteModel, setDefaultModel, getProviders } from "@/lib/api"
import { useI18n } from "@/i18n"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ErrorAlertDialog, useErrorAlert } from "@/components/ui/error-alert-dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Badge } from "@/components/ui/badge"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

type ProviderConfigDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

// All model types for frontend configuration
const MODEL_TYPES: ModelType[] = ["llm", "vlm", "embedding"]

// Model change state type
type ModelChanges = {
  api_key?: string
  thinking?: boolean
  is_active?: boolean
  is_default?: boolean
}

export function ProviderConfigDialog({ open, onOpenChange }: ProviderConfigDialogProps) {
  const { t } = useI18n()
  const [models, setModels] = useState<ModelInfo[]>([])
  const [providers, setProviders] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [showNewModelForm, setShowNewModelForm] = useState(false)
  // Track models being deleted for smooth animation
  const [deletingModelIds, setDeletingModelIds] = useState<Set<string>>(new Set())

  // New model form state
  const [newModel, setNewModel] = useState<ModelCreate>({
    provider: "",
    model_type: "llm",
    model_id: "",
    model_name: "",
    api_key: "",
    thinking: false,
    is_default: false,
    is_active: true,
  })

  // New model API Key visibility state
  const [newModelApiKeyVisible, setNewModelApiKeyVisible] = useState(false)

  // API Key editing state (model_id -> raw value)
  const [apiKeyEdits, setApiKeyEdits] = useState<Record<string, string>>({})

  // Default model selection state
  const [selectedDefaultLLM, setSelectedDefaultLLM] = useState<string>("")
  const [selectedDefaultVLM, setSelectedDefaultVLM] = useState<string>("")
  const [selectedDefaultEmbedding, setSelectedDefaultEmbedding] = useState<string>("")
  const [hasDefaultChanges, setHasDefaultChanges] = useState(false)

  // Pending changes state (model_id -> changes)
  const [pendingChanges, setPendingChanges] = useState<Record<string, ModelChanges>>({})

  // Error alert hook
  const errorAlert = useErrorAlert()

  // Load models and providers on dialog open
  const loadData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [modelsResult, providersResult] = await Promise.all([
        getAllModels(),
        getProviders(),
      ])
      // All model types are now configurable (llm, vlm, embedding)
      setModels(modelsResult.models)
      setProviders(providersResult.providers)

      // Initialize default model selections
      const defaultLLM = modelsResult.models.find(m => m.model_type === "llm" && m.is_default)
      const defaultVLM = modelsResult.models.find(m => m.model_type === "vlm" && m.is_default)
      const defaultEmbedding = modelsResult.models.find(m => m.model_type === "embedding" && m.is_default)
      setSelectedDefaultLLM(defaultLLM?.model_id || "")
      setSelectedDefaultVLM(defaultVLM?.model_id || "")
      setSelectedDefaultEmbedding(defaultEmbedding?.model_id || "")
      setHasDefaultChanges(false)
    } catch (error) {
      console.error("Failed to load data:", error)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      void loadData()
      // Reset states when dialog opens
      setApiKeyEdits({})
      setPendingChanges({})
    }
  }, [open, loadData])

  // Handle API key edit
  const handleApiKeyChange = (modelId: string, value: string) => {
    setApiKeyEdits(prev => ({
      ...prev,
      [modelId]: value,
    }))
    // Track as pending change
    setPendingChanges(prev => ({
      ...prev,
      [modelId]: { ...prev[modelId], api_key: value },
    }))
  }

  // Handle switch change
  const handleSwitchChange = (modelId: string, field: keyof ModelChanges, value: boolean) => {
    setPendingChanges(prev => ({
      ...prev,
      [modelId]: { ...prev[modelId], [field]: value },
    }))
  }

  // Check if model has pending changes
  const hasPendingChanges = (modelId: string): boolean => {
    const changes = pendingChanges[modelId]
    if (!changes) return false
    return Object.keys(changes).length > 0
  }

  // Cancel pending changes for a model
  const cancelChanges = (modelId: string) => {
    setPendingChanges(prev => {
      const next = { ...prev }
      delete next[modelId]
      return next
    })
    setApiKeyEdits(prev => {
      const next = { ...prev }
      delete next[modelId]
      return next
    })
  }

  // Save all pending changes for a model
  const saveChanges = async (modelId: string) => {
    const changes = pendingChanges[modelId]
    if (!changes || Object.keys(changes).length === 0) return

    try {
      // Build update data (API key sent as-is, HTTPS provides encryption)
      const updateData: ModelUpdate = {}
      if (changes.api_key !== undefined) {
        updateData.api_key = changes.api_key
      }
      if (changes.thinking !== undefined) {
        updateData.thinking = changes.thinking
      }
      if (changes.is_active !== undefined) {
        updateData.is_active = changes.is_active
      }
      if (changes.is_default !== undefined) {
        updateData.is_default = changes.is_default
      }

      if (Object.keys(updateData).length > 0) {
        if (updateData.is_default) {
          await setDefaultModel(modelId)
        }
        await updateModel(modelId, updateData)
      }

      // Clear pending changes
      setPendingChanges(prev => {
        const next = { ...prev }
        delete next[modelId]
        return next
      })
      setApiKeyEdits(prev => {
        const next = { ...prev }
        delete next[modelId]
        return next
      })

      await loadData()
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      // Check for specific error types
      if (errorMessage.includes("model_name_exists")) {
        errorAlert.showError(t("error.modelNameExists"))
      } else {
        errorAlert.showError(t("error.saveFailed", { details: errorMessage }))
      }
      console.error("Failed to save changes:", error)
    }
  }

  // Create new model
  const handleCreateModel = async () => {
    if (!newModel.model_id || !newModel.provider || !newModel.model_name) return

    try {
      // Send API key as-is (HTTPS provides encryption in transit)
      await createModel(newModel)
      setNewModel({
        provider: "",
        model_type: "llm",
        model_id: "",
        model_name: "",
        api_key: "",
        thinking: false,
        is_default: false,
        is_active: true,
      })
      setShowNewModelForm(false)
      await loadData()
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      // Check for specific error types
      if (errorMessage.includes("model_id_exists")) {
        errorAlert.showError(t("error.modelIdExists"))
      } else if (errorMessage.includes("model_name_exists")) {
        errorAlert.showError(t("error.modelNameExists"))
      } else {
        errorAlert.showError(t("error.createFailed", { details: errorMessage }))
      }
      console.error("Failed to create model:", error)
    }
  }

  // Delete model - smooth delete with animation
  const handleDeleteModel = async (modelId: string) => {
    // Mark as deleting for fade-out animation
    setDeletingModelIds(prev => new Set(prev).add(modelId))

    // Wait for fade-out animation (300ms)
    await new Promise(resolve => setTimeout(resolve, 300))

    try {
      await deleteModel(modelId)
      // Remove from local state immediately for smooth UI update
      setModels(prev => prev.filter(m => m.model_id !== modelId))
      // Clear pending changes for deleted model
      setPendingChanges(prev => {
        const next = { ...prev }
        delete next[modelId]
        return next
      })
      setApiKeyEdits(prev => {
        const next = { ...prev }
        delete next[modelId]
        return next
      })
    } catch (error) {
      console.error("Failed to delete model:", error)
      // Restore model on error - need to reload
      await loadData()
    } finally {
      // Clear deleting state
      setDeletingModelIds(prev => {
        const next = new Set(prev)
        next.delete(modelId)
        return next
      })
    }
  }

  // Handle model_id change - auto-fill model_name
  const handleModelIdChange = (value: string) => {
    setNewModel(prev => ({
      ...prev,
      model_id: value,
      model_name: prev.model_name || value.split("/").pop() || value,
    }))
  }

  // Handle model_type change
  const handleModelTypeChange = (value: ModelType) => {
    setNewModel(prev => ({
      ...prev,
      model_type: value,
    }))
  }

  // Get effective value for a model field (pending change or original)
  const getEffectiveValue = (model: ModelInfo, field: keyof ModelChanges): unknown => {
    const changes = pendingChanges[model.model_id]
    if (changes && changes[field] !== undefined) {
      return changes[field]
    }
    return model[field as keyof ModelInfo]
  }

  // Handle default model selection change
  const handleDefaultLLMChange = (value: string) => {
    // Treat __none__ as empty string
    setSelectedDefaultLLM(value === "__none__" ? "" : value)
    setHasDefaultChanges(true)
  }

  const handleDefaultVLMChange = (value: string) => {
    // Treat __none__ as empty string
    setSelectedDefaultVLM(value === "__none__" ? "" : value)
    setHasDefaultChanges(true)
  }

  const handleDefaultEmbeddingChange = (value: string) => {
    // Treat __none__ as empty string
    setSelectedDefaultEmbedding(value === "__none__" ? "" : value)
    setHasDefaultChanges(true)
  }

  // Save default model changes
  const saveDefaultChanges = async () => {
    try {
      // Update default LLM (use empty string if __none__)
      const currentDefaultLLM = models.find(m => m.model_type === "llm" && m.is_default)
      const newDefaultLLM = selectedDefaultLLM || undefined
      if (newDefaultLLM && newDefaultLLM !== currentDefaultLLM?.model_id) {
        await setDefaultModel(newDefaultLLM)
      }

      // Update default VLM (use empty string if __none__)
      const currentDefaultVLM = models.find(m => m.model_type === "vlm" && m.is_default)
      const newDefaultVLM = selectedDefaultVLM || undefined
      if (newDefaultVLM && newDefaultVLM !== currentDefaultVLM?.model_id) {
        await setDefaultModel(newDefaultVLM)
      }

      // Update default Embedding (use empty string if __none__)
      const currentDefaultEmbedding = models.find(m => m.model_type === "embedding" && m.is_default)
      const newDefaultEmbedding = selectedDefaultEmbedding || undefined
      if (newDefaultEmbedding && newDefaultEmbedding !== currentDefaultEmbedding?.model_id) {
        await setDefaultModel(newDefaultEmbedding)
      }

      setHasDefaultChanges(false)
      await loadData()
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      errorAlert.showError(errorMessage)
      console.error("Failed to save default changes:", error)
    }
  }

  // Cancel default model changes
  const cancelDefaultChanges = () => {
    const defaultLLM = models.find(m => m.model_type === "llm" && m.is_default)
    const defaultVLM = models.find(m => m.model_type === "vlm" && m.is_default)
    const defaultEmbedding = models.find(m => m.model_type === "embedding" && m.is_default)
    setSelectedDefaultLLM(defaultLLM?.model_id || "")
    setSelectedDefaultVLM(defaultVLM?.model_id || "")
    setSelectedDefaultEmbedding(defaultEmbedding?.model_id || "")
    setHasDefaultChanges(false)
  }

  return (
    <>
      {/* Error Alert Dialog - Centered on screen */}
      <ErrorAlertDialog state={errorAlert.state} onOpenChange={errorAlert.setOpen} />

      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent style={{ maxWidth: '90vw', width: 'max-content' }} className="dialog-scroll-area max-h-[85vh] overflow-y-auto
                                   bg-gradient-to-br from-background via-background to-muted/30
                                   dark:bg-gradient-to-br dark:from-[#0B0F1A] dark:via-[#111827] dark:to-[#1A2238]/50
                                   dark:border-primary/20 dark:backdrop-blur-xl
                                   shadow-2xl dark:shadow-[0_0_40px_rgba(0,209,255,0.1)]
                                   rounded-2xl">
          <DialogHeader className="pb-4 border-b border-border/50">
            <DialogTitle className="flex items-center gap-3 text-lg">
              <div className="size-9 rounded-xl bg-gradient-to-br from-primary/20 to-accent/20 
                               flex items-center justify-center
                               shadow-[0_0_12px_rgba(0,209,255,0.2)]">
                <Settings2 className="size-5 text-primary" />
              </div>
              <span className="bg-gradient-to-r from-foreground to-foreground/80 bg-clip-text">
                {t("provider.configTitle")}
              </span>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <a
                      href="https://docs.litellm.ai/docs/providers"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-muted-foreground hover:text-primary transition-colors p-1.5 rounded-lg hover:bg-primary/10"
                    >
                      <HelpCircle className="size-4" />
                    </a>
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-xs">
                    <p>{t("provider.helpLink") || "View provider documentation"}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </DialogTitle>
            <DialogDescription className="text-muted-foreground/80 ml-12">
              {t("provider.configDescription")}
            </DialogDescription>
          </DialogHeader>

          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Header Row: Default Model Selectors - LLM, VLM, Embedding */}
              <div className="flex items-center justify-between gap-3 flex-wrap">
                {/* Left side: LLM + VLM + Embedding */}
                <div className="flex items-center gap-3">
                  {/* Default LLM Select */}
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-muted-foreground whitespace-nowrap">{t("model.defaultLLM")}:</span>
                    <Select
                      value={selectedDefaultLLM || "__none__"}
                      onValueChange={handleDefaultLLMChange}
                    >
                      <SelectTrigger className="w-36 h-8 rounded-lg text-xs">
                        <SelectValue placeholder={t("model.selectPlaceholder")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__" className="text-xs">{t("model.none")}</SelectItem>
                        {models.filter(m => m.model_type === "llm" && m.is_active).map(m => (
                          <SelectItem key={m.model_id} value={m.model_id} className="text-xs">
                            {m.model_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Default VLM Select */}
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-muted-foreground whitespace-nowrap">{t("model.defaultVLM")}:</span>
                    <Select
                      value={selectedDefaultVLM || "__none__"}
                      onValueChange={handleDefaultVLMChange}
                    >
                      <SelectTrigger className="w-36 h-8 rounded-lg text-xs">
                        <SelectValue placeholder={t("model.selectPlaceholder")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__" className="text-xs">{t("model.none")}</SelectItem>
                        {models.filter(m => m.model_type === "vlm" && m.is_active).map(m => (
                          <SelectItem key={m.model_id} value={m.model_id} className="text-xs">
                            {m.model_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Default Embedding Select */}
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-muted-foreground whitespace-nowrap">{t("model.defaultEmbedding")}:</span>
                    <Select
                      value={selectedDefaultEmbedding || "__none__"}
                      onValueChange={handleDefaultEmbeddingChange}
                    >
                      <SelectTrigger className="w-36 h-8 rounded-lg text-xs">
                        <SelectValue placeholder={t("model.selectPlaceholder")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__" className="text-xs">{t("model.none")}</SelectItem>
                        {models.filter(m => m.model_type === "embedding" && m.is_active).map(m => (
                          <SelectItem key={m.model_id} value={m.model_id} className="text-xs">
                            {m.model_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                {/* Right side: Save/Cancel Buttons */}
                {hasDefaultChanges && (
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={cancelDefaultChanges}
                      className="h-8 px-2 text-xs"
                    >
                      {t("common.cancel")}
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => void saveDefaultChanges()}
                      className="h-8 px-3 text-xs rounded-lg
                                 bg-gradient-to-r from-primary to-accent
                                 hover:from-primary/90 hover:to-accent/90
                                 shadow-[0_0_8px_rgba(0,209,255,0.3)]
                                 transition-all duration-200"
                    >
                      {t("common.save")}
                    </Button>
                  </div>
                )}
              </div>

              {/* New Model Form */}
              {showNewModelForm && (
                <div className="border border-primary/20 dark:border-primary/30 rounded-2xl p-5 space-y-5 
                                bg-gradient-to-br from-muted/50 to-muted/30 
                                dark:bg-gradient-to-br dark:from-primary/5 dark:to-accent/5
                                shadow-lg dark:shadow-[0_0_20px_rgba(0,209,255,0.08)]
                                animate-in fade-in-0 slide-in-from-top-4 duration-300">
                  <h4 className="font-semibold text-base flex items-center gap-2">
                    <div className="size-6 rounded-lg bg-primary/10 flex items-center justify-center">
                      <Plus className="size-3.5 text-primary" />
                    </div>
                    {t("model.new") || "New Model"}
                  </h4>

                  {/* Row 1: Provider and Model Type */}
                  <div className="grid grid-cols-2 gap-4">
                    {/* Provider */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium flex items-center gap-1">
                        {t("model.provider")}
                        <a
                          href="https://docs.litellm.ai/docs/providers"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-muted-foreground hover:text-foreground transition-colors"
                          title={t("provider.helpLink") || "View provider documentation"}
                        >
                          <HelpCircle className="size-3.5" />
                        </a>
                      </label>
                      <Select
                        value={newModel.provider}
                        onValueChange={(value) => setNewModel(prev => ({ ...prev, provider: value }))}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select provider" />
                        </SelectTrigger>
                        <SelectContent>
                          {providers.map(p => (
                            <SelectItem key={p} value={p}>{p}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    {/* Model Type */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium">{t("model.type") || "Model Type"}</label>
                      <Select
                        value={newModel.model_type}
                        onValueChange={handleModelTypeChange}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {MODEL_TYPES.map(type => (
                            <SelectItem key={type} value={type}>
                              {type.toUpperCase()}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  {/* Row 2: API Key */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">API Key</label>
                    <div className="relative">
                      <Input
                        type={newModelApiKeyVisible ? "text" : "password"}
                        placeholder={t("provider.apiKeyPlaceholder")}
                        value={newModel.api_key || ""}
                        onChange={(e) => setNewModel(prev => ({ ...prev, api_key: e.target.value }))}
                        className="pr-10"
                      />
                      <button
                        type="button"
                        onClick={() => setNewModelApiKeyVisible(!newModelApiKeyVisible)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      >
                        {newModelApiKeyVisible ? (
                          <EyeOff className="size-4" />
                        ) : (
                          <Eye className="size-4" />
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Row 3: Model ID and Model Name */}
                  <div className="grid grid-cols-2 gap-4">
                    {/* Model ID */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Model ID</label>
                      <Input
                        placeholder="qwen3.5-27b"
                        value={newModel.model_id}
                        onChange={(e) => handleModelIdChange(e.target.value)}
                      />
                    </div>

                    {/* Model Name */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Model Name</label>
                      <Input
                        placeholder="qwen3.5-27b"
                        value={newModel.model_name}
                        onChange={(e) => setNewModel(prev => ({ ...prev, model_name: e.target.value }))}
                      />
                    </div>
                  </div>

                  {/* Row 4: Thinking, Active, Default switches */}
                  <div className="flex items-center gap-4 flex-wrap">
                    {/* Thinking Switch - only for llm/vlm, not embedding */}
                    {newModel.model_type !== "embedding" && (
                      <div className="flex items-center gap-2">
                        <Switch
                          id="new-thinking"
                          checked={newModel.thinking}
                          onCheckedChange={(checked: boolean) => setNewModel(prev => ({ ...prev, thinking: checked }))}
                        />
                        <label htmlFor="new-thinking" className="text-sm">{t("model.thinking")}</label>
                      </div>
                    )}

                    {/* Is Active */}
                    <div className="flex items-center gap-2">
                      <Switch
                        id="new-active"
                        checked={newModel.is_active}
                        onCheckedChange={(checked: boolean) => setNewModel(prev => ({ ...prev, is_active: checked }))}
                      />
                      <label htmlFor="new-active" className="text-sm">{t("model.active")}</label>
                    </div>

                    {/* Is Default */}
                    <div className="flex items-center gap-2">
                      <Switch
                        id="new-default"
                        checked={newModel.is_default}
                        onCheckedChange={(checked: boolean) => setNewModel(prev => ({ ...prev, is_default: checked }))}
                      />
                      <label htmlFor="new-default" className="text-sm">
                        {t("model.default")}
                      </label>
                    </div>
                  </div>

                  <div className="flex justify-end gap-2">
                    <Button variant="outline" onClick={() => setShowNewModelForm(false)}>
                      {t("common.cancel")}
                    </Button>
                    <Button onClick={handleCreateModel} disabled={!newModel.model_id?.trim() || !newModel.provider?.trim() || !newModel.model_name?.trim() || !newModel.api_key?.trim()}>
                      {t("common.save")}
                    </Button>
                  </div>
                </div>
              )}

              <Separator />

              {/* Models List - Grouped by provider (sorted alphabetically) */}
              <div className="space-y-6">
                {Array.from(new Set(models.map(m => m.provider))).sort().map(provider => {
                  const providerModels = models
                    .filter(m => m.provider === provider)
                    .sort((a, b) => a.model_name.localeCompare(b.model_name))

                  return (
                    <div key={provider} className="space-y-3">
                      <h4 className="font-semibold text-sm text-muted-foreground uppercase tracking-wide flex items-center gap-2">
                        <Badge variant="secondary">{provider}</Badge>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-6 rounded-lg text-muted-foreground hover:text-primary hover:bg-primary/10"
                          onClick={() => {
                            setNewModel(prev => ({ ...prev, provider, model_type: "llm" }))
                            setShowNewModelForm(true)
                          }}
                        >
                          <Plus className="size-3.5" />
                        </Button>
                      </h4>
                      {providerModels.map(model => {
                        const hasChanges = hasPendingChanges(model.model_id)
                        const effectiveThinking = getEffectiveValue(model, "thinking") as boolean
                        const effectiveActive = getEffectiveValue(model, "is_active") as boolean
                        const isDeleting = deletingModelIds.has(model.model_id)

                        return (
                          <div
                            key={model.model_id}
                            className="group border border-border/50 dark:border-primary/10 
                                       rounded-2xl p-5 space-y-4 
                                       bg-card/50 dark:bg-gradient-to-br dark:from-white/[0.03] dark:to-white/[0.01]
                                       dark:backdrop-blur-sm
                                       hover:border-primary/30 dark:hover:border-primary/30
                                       hover:shadow-lg dark:hover:shadow-[0_0_20px_rgba(0,209,255,0.08)]
                                       transition-all duration-300 ease-out"
                            style={{
                              opacity: isDeleting ? 0 : 1,
                              transform: isDeleting ? 'scale(0.95)' : 'scale(1)',
                              height: isDeleting ? 0 : 'auto',
                              overflow: 'hidden',
                              marginBottom: isDeleting ? 0 : undefined,
                              padding: isDeleting ? 0 : undefined,
                            }}
                          >
                            {/* Model Header - Model Name, Type, Switches, and Delete Button on same line */}
                            <div className="flex items-center justify-between gap-3 flex-wrap">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-semibold text-base">{model.model_name}</span>
                                <Badge
                                  variant="outline"
                                  className="rounded-lg px-2.5 py-0.5 text-xs font-medium
                                             border-primary/30 text-primary
                                             dark:border-primary/40 dark:text-primary"
                                >
                                  {model.model_type.toUpperCase()}
                                </Badge>
                                {model.is_default && (
                                  <Badge
                                    variant="secondary"
                                    className="rounded-lg px-2 py-0.5 text-xs font-medium
                                               bg-warm/10 text-warm border-warm/20"
                                  >
                                    {t("model.default")}
                                  </Badge>
                                )}

                                {/* Thinking Switch - only show for llm/vlm, not embedding */}
                                {model.model_type !== "embedding" && (
                                  <div className="flex items-center gap-1.5 ml-1">
                                    <Switch
                                      id={`thinking-${model.model_id}`}
                                      checked={effectiveThinking}
                                      onCheckedChange={(checked: boolean) => handleSwitchChange(model.model_id, "thinking", checked)}
                                      className="scale-75"
                                    />
                                    <label htmlFor={`thinking-${model.model_id}`}
                                      className="text-xs text-muted-foreground cursor-pointer">
                                      {t("model.thinking")}
                                    </label>
                                  </div>
                                )}

                                {/* Active Switch - moved to header row */}
                                <div className="flex items-center gap-1.5">
                                  <Switch
                                    id={`active-${model.model_id}`}
                                    checked={effectiveActive}
                                    onCheckedChange={(checked: boolean) => handleSwitchChange(model.model_id, "is_active", checked)}
                                    className="scale-75"
                                  />
                                  <label htmlFor={`active-${model.model_id}`}
                                    className="text-xs text-muted-foreground cursor-pointer">
                                    {t("model.active")}
                                  </label>
                                </div>
                              </div>

                              {/* Delete Button - Right side - Direct delete */}
                              <Button
                                variant="ghost"
                                size="icon"
                                className="size-9 rounded-xl text-destructive/60 hover:text-destructive 
                                           hover:bg-destructive/10 hover:shadow-[0_0_8px_rgba(239,68,68,0.2)]
                                           transition-all duration-200"
                                onClick={() => void handleDeleteModel(model.model_id)}
                              >
                                <Trash2 className="size-4" />
                              </Button>
                            </div>

                            {/* API Key */}
                            <div className="space-y-1.5">
                              <label className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                                <div className="size-1 rounded-full bg-primary/50" />
                                API Key
                              </label>
                              <Input
                                type="password"
                                placeholder={model.has_api_key ? "••••••••••••" : t("provider.apiKeyPlaceholder")}
                                value={apiKeyEdits[model.model_id] ?? ""}
                                onChange={(e) => handleApiKeyChange(model.model_id, e.target.value)}
                                className="rounded-xl bg-muted/50 dark:bg-white/5 
                                           border-border/50 dark:border-primary/10
                                           focus:border-primary/50 dark:focus:border-primary/30
                                           focus:ring-primary/20 dark:focus:ring-primary/10
                                           transition-all duration-200"
                              />
                            </div>


                            {/* Cancel/Save Buttons - Only show when there are pending changes */}
                            {hasChanges && (
                              <div className="flex justify-end gap-2.5 pt-3 border-t border-border/50 dark:border-primary/10">
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => cancelChanges(model.model_id)}
                                  className="rounded-xl px-4"
                                >
                                  {t("common.cancel")}
                                </Button>
                                <Button
                                  size="sm"
                                  onClick={() => void saveChanges(model.model_id)}
                                  className="rounded-xl px-4 
                                             bg-gradient-to-r from-primary to-accent
                                             hover:from-primary/90 hover:to-accent/90
                                             shadow-[0_0_12px_rgba(0,209,255,0.3)]
                                             hover:shadow-[0_0_16px_rgba(0,209,255,0.4)]
                                             transition-all duration-200"
                                >
                                  {t("common.save")}
                                </Button>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )
                })}

                {models.length === 0 && (
                  <div className="text-center py-8 text-muted-foreground">
                    No models configured. Click "Add Model" to add one.
                  </div>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
