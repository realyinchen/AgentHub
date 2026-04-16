import { useState, useEffect, useCallback } from "react"
import { Eye, EyeOff, Plus, Trash2, Star, Settings2, HelpCircle } from "lucide-react"

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
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

type ProviderConfigDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

// Only LLM and VLM types for frontend configuration
const MODEL_TYPES: ModelType[] = ["llm", "vlm"]

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
      // Filter out embedding models - they are configured via .env
      const configurableModels = modelsResult.models.filter(m => m.model_type !== "embedding")
      setModels(configurableModels)
      setProviders(providersResult.providers)
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
        errorAlert.showError("Model Name 已存在，请使用其他名称")
      } else {
        errorAlert.showError(errorMessage)
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
        errorAlert.showError("Model ID 已存在，请使用其他 ID")
      } else if (errorMessage.includes("model_name_exists")) {
        errorAlert.showError("Model Name 已存在，请使用其他名称")
      } else {
        errorAlert.showError(errorMessage)
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

  return (
    <>
      {/* Error Alert Dialog - Centered on screen */}
      <ErrorAlertDialog state={errorAlert.state} onOpenChange={errorAlert.setOpen} />

      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="dialog-scroll-area max-w-5xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings2 className="size-5" />
            {t("provider.configTitle")}
            <a
              href="https://docs.litellm.ai/docs/providers"
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted-foreground hover:text-foreground transition-colors"
              title={t("provider.helpLink") || "View provider documentation"}
            >
              <HelpCircle className="size-4" />
            </a>
          </DialogTitle>
          <DialogDescription>
            {t("provider.configDescription")}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          </div>
        ) : (
          <div className="space-y-4">
            {/* New Model Button */}
            <div className="flex justify-end">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowNewModelForm(!showNewModelForm)}
                className="gap-1"
              >
                <Plus className="size-4" />
                {t("common.add") || "Add Model"}
              </Button>
            </div>

            {/* New Model Form */}
            {showNewModelForm && (
              <div className="border rounded-lg p-4 space-y-4 bg-muted/50">
                <h4 className="font-medium">{t("model.new") || "New Model"}</h4>

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
                  {/* Thinking Switch */}
                  <div className="flex items-center gap-2">
                    <Switch
                      id="new-thinking"
                      checked={newModel.thinking}
                      onCheckedChange={(checked: boolean) => setNewModel(prev => ({ ...prev, thinking: checked }))}
                    />
                    <label htmlFor="new-thinking" className="text-sm">{t("model.thinking")}</label>
                  </div>

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
                    <label htmlFor="new-default" className="text-sm flex items-center gap-1">
                      <Star className="size-3" />
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
                    </h4>
                    {providerModels.map(model => {
                      const hasChanges = hasPendingChanges(model.model_id)
                      const effectiveThinking = getEffectiveValue(model, "thinking") as boolean
                      const effectiveActive = getEffectiveValue(model, "is_active") as boolean
                      const effectiveDefault = getEffectiveValue(model, "is_default") as boolean
                      const isDeleting = deletingModelIds.has(model.model_id)

                      return (
                        <div
                          key={model.model_id}
                          className="border rounded-lg p-4 space-y-3 transition-all duration-300 ease-out"
                          style={{
                            opacity: isDeleting ? 0 : 1,
                            transform: isDeleting ? 'scale(0.95)' : 'scale(1)',
                            height: isDeleting ? 0 : 'auto',
                            overflow: 'hidden',
                            marginBottom: isDeleting ? 0 : undefined,
                            padding: isDeleting ? 0 : undefined,
                          }}
                        >
                          {/* Model Header - Model Name, Type, and Delete Button on same line */}
                           <div className="flex items-center justify-between gap-2 flex-wrap">
                             <div className="flex items-center gap-2 flex-wrap">
                               <span className="font-medium">{model.model_name}</span>
                               <Badge variant="outline">{model.model_type.toUpperCase()}</Badge>
                              {model.thinking && (
                                <Badge variant="secondary">{t("model.thinking")}</Badge>
                              )}
                              {model.is_default && (
                                <Star className="size-4 text-yellow-500 fill-yellow-500" />
                              )}
                            </div>

                            {/* Delete Button - Right side - Direct delete */}
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-8 text-destructive hover:text-destructive"
                              onClick={() => void handleDeleteModel(model.model_id)}
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          </div>

                          {/* API Key */}
                          <div className="space-y-1">
                            <label className="text-xs text-muted-foreground">API Key</label>
                            <Input
                              type="password"
                              placeholder={model.has_api_key ? "••••••••••••" : t("provider.apiKeyPlaceholder")}
                              value={apiKeyEdits[model.model_id] ?? ""}
                              onChange={(e) => handleApiKeyChange(model.model_id, e.target.value)}
                            />
                          </div>

                          {/* Switches */}
                          <div className="flex items-center justify-between flex-wrap gap-2">
                            <div className="flex items-center gap-4 flex-wrap">
                              <TooltipProvider>
                                {/* Thinking Switch */}
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <div className="flex items-center gap-2">
                                      <Switch
                                        id={`thinking-${model.model_id}`}
                                        checked={effectiveThinking}
                                        onCheckedChange={(checked: boolean) => handleSwitchChange(model.model_id, "thinking", checked)}
                                      />
                                      <label htmlFor={`thinking-${model.model_id}`} className="text-sm">{t("model.thinking")}</label>
                                    </div>
                                  </TooltipTrigger>
                                </Tooltip>
                              </TooltipProvider>

                              {/* Active Switch */}
                              <div className="flex items-center gap-2">
                                <Switch
                                  id={`active-${model.model_id}`}
                                  checked={effectiveActive}
                                  onCheckedChange={(checked: boolean) => handleSwitchChange(model.model_id, "is_active", checked)}
                                />
                                <label htmlFor={`active-${model.model_id}`} className="text-sm">{t("model.active")}</label>
                              </div>

                              {/* Default Switch */}
                              <div className="flex items-center gap-2">
                                <Switch
                                  id={`default-${model.model_id}`}
                                  checked={effectiveDefault}
                                  onCheckedChange={(checked: boolean) => handleSwitchChange(model.model_id, "is_default", checked)}
                                />
                                <label htmlFor={`default-${model.model_id}`} className="text-sm flex items-center gap-1">
                                  <Star className="size-3" />
                                  {t("model.default")}
                                </label>
                              </div>
                            </div>
                          </div>

                          {/* Cancel/Save Buttons - Only show when there are pending changes */}
                          {hasChanges && (
                            <div className="flex justify-end gap-2 pt-2 border-t">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => cancelChanges(model.model_id)}
                              >
                                {t("common.cancel")}
                              </Button>
                              <Button
                                size="sm"
                                onClick={() => void saveChanges(model.model_id)}
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
