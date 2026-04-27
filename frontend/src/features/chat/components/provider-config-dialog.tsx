import { useState, useEffect, useCallback } from "react"
import { Eye, EyeOff, Plus, Trash2, Settings2, HelpCircle, Edit2, ChevronRight, ChevronDown, Server, AlertTriangle } from "lucide-react"

import type { ModelInfo, ModelType, ModelCreate, ModelUpdate, ProviderInfo, ProviderUpdate } from "@/types"
import { getAllModels, createModel, updateModel, deleteModel, setDefaultModel, getProviders, updateProvider } from "@/lib/api"
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

const MODEL_TYPES: ModelType[] = ["llm", "vlm", "embedding"]

type ModelChanges = {
  model_id?: string
  model_type?: ModelType
  thinking?: boolean
  is_active?: boolean
  is_default?: boolean
}

// Editable new model form with unique id
type EditableNewModel = {
  id: string
  data: ModelCreate
}

const getDisplayName = (modelId: string): string => {
  return modelId.split("/").pop() || modelId
}

export function ProviderConfigDialog({ open, onOpenChange }: ProviderConfigDialogProps) {
  const { t } = useI18n()
  const [models, setModels] = useState<ModelInfo[]>([])
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [expandedProviders, setExpandedProviders] = useState<Set<string>>(new Set())
  const [deletingModelIds, setDeletingModelIds] = useState<Set<string>>(new Set())
  const [editingModelIds, setEditingModelIds] = useState<Set<string>>(new Set())

  // Provider editing state
  const [providerApiKeyEdits, setProviderApiKeyEdits] = useState<Record<string, string>>({})
  const [providerBaseUrlEdits, setProviderBaseUrlEdits] = useState<Record<string, string>>({})
  const [providerApiKeyVisible, setProviderApiKeyVisible] = useState<Record<string, boolean>>({})

  // Multiple editable new model forms
  const [newModelForms, setNewModelForms] = useState<EditableNewModel[]>([])

  const [modelIdEdits, setModelIdEdits] = useState<Record<string, string>>({})
  const [modelTypeEdits, setModelTypeEdits] = useState<Record<string, ModelType>>({})
  const [pendingChanges, setPendingChanges] = useState<Record<string, ModelChanges>>({})

  // Unsaved changes confirmation dialog state
  const [pendingProviderSwitch, setPendingProviderSwitch] = useState<string | null>(null)

  const errorAlert = useErrorAlert()

  // Check if current provider has unsaved changes
  const hasUnsavedProviderChanges = (provider: string): boolean => {
    return providerApiKeyEdits[provider] !== undefined || providerBaseUrlEdits[provider] !== undefined
  }

  const loadData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [modelsResult, providersResult] = await Promise.all([
        getAllModels(),
        getProviders(),
      ])
      setModels(modelsResult.models)
      setProviders(providersResult.providers)
    } catch (error) {
      console.error("Failed to load data:", error)
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Auto-select first provider when data is loaded and no provider is selected
  useEffect(() => {
    if (providers.length > 0 && !selectedProvider) {
      setSelectedProvider(providers[0].provider)
    }
  }, [providers, selectedProvider])

  useEffect(() => {
    if (open) {
      void loadData()
      setPendingChanges({})
      setNewModelForms([])
    }
  }, [open, loadData])

  // Provider expand/collapse toggle
  const toggleProviderExpand = (provider: string) => {
    setExpandedProviders(prev => {
      const next = new Set(prev)
      if (next.has(provider)) {
        next.delete(provider)
      } else {
        next.add(provider)
      }
      return next
    })
  }

  // Provider API Key handlers
  const handleProviderApiKeyChange = (provider: string, value: string) => {
    setProviderApiKeyEdits(prev => ({ ...prev, [provider]: value }))
  }

  const handleProviderBaseUrlChange = (provider: string, value: string) => {
    setProviderBaseUrlEdits(prev => ({ ...prev, [provider]: value }))
  }

  const toggleProviderApiKeyVisible = (provider: string) => {
    setProviderApiKeyVisible(prev => ({ ...prev, [provider]: !prev[provider] }))
  }

  const saveProviderConfig = async (providerName: string) => {
    const updateData: ProviderUpdate = { provider: providerName }
    const apiKey = providerApiKeyEdits[providerName]
    const baseUrl = providerBaseUrlEdits[providerName]

    if (apiKey !== undefined && apiKey.trim() !== "") {
      updateData.api_key = apiKey
    }
    if (baseUrl !== undefined) {
      updateData.base_url = baseUrl.trim() || null
    }

    if (updateData.api_key || updateData.base_url !== undefined) {
      try {
        await updateProvider(updateData)
        // Clear edits
        setProviderApiKeyEdits(prev => { const n = { ...prev }; delete n[providerName]; return n })
        setProviderBaseUrlEdits(prev => { const n = { ...prev }; delete n[providerName]; return n })
        // Refresh
        const providersResult = await getProviders()
        setProviders(providersResult.providers)
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error)
        errorAlert.showError(t("error.saveFailed", { details: errorMessage }))
      }
    }
  }

  // Model handlers
  const handleModelIdChange = (modelId: string, value: string) => {
    setModelIdEdits(prev => ({ ...prev, [modelId]: value }))
    setPendingChanges(prev => ({ ...prev, [modelId]: { ...prev[modelId], model_id: value } }))
  }

  const handleModelTypeChangeForEdit = (modelId: string, value: ModelType) => {
    setModelTypeEdits(prev => ({ ...prev, [modelId]: value }))
    setPendingChanges(prev => ({ ...prev, [modelId]: { ...prev[modelId], model_type: value } }))
  }

  const handleSwitchChange = (modelId: string, field: keyof ModelChanges, value: boolean) => {
    setPendingChanges(prev => ({ ...prev, [modelId]: { ...prev[modelId], [field]: value } }))
  }

  const hasPendingChanges = (modelId: string): boolean => {
    const changes = pendingChanges[modelId]
    return changes ? Object.keys(changes).length > 0 : false
  }

  const cancelChanges = (modelId: string) => {
    setPendingChanges(prev => { const n = { ...prev }; delete n[modelId]; return n })
    setModelIdEdits(prev => { const n = { ...prev }; delete n[modelId]; return n })
    setModelTypeEdits(prev => { const n = { ...prev }; delete n[modelId]; return n })
    setEditingModelIds(prev => { const n = new Set(prev); n.delete(modelId); return n })
  }

  const saveChanges = async (modelId: string) => {
    const changes = pendingChanges[modelId]
    if (!changes || Object.keys(changes).length === 0) return

    try {
      const model = models.find(m => m.model_id === modelId)
      if (!model) throw new Error("Model not found")

      const updateData: ModelUpdate = {}
      if (changes.model_id !== undefined && changes.model_id.trim()) {
        const newModelId = changes.model_id.trim()
        updateData.model_id = newModelId.includes("/") ? newModelId : `${model.provider}/${newModelId}`
      }
      if (changes.model_type !== undefined) updateData.model_type = changes.model_type
      if (changes.thinking !== undefined) updateData.thinking = changes.thinking
      if (changes.is_active !== undefined) updateData.is_active = changes.is_active
      if (changes.is_default !== undefined) updateData.is_default = changes.is_default

      if (Object.keys(updateData).length > 0) {
        if (updateData.is_default) await setDefaultModel(model.id)
        await updateModel(model.id, updateData)
      }

      setPendingChanges(prev => { const n = { ...prev }; delete n[modelId]; return n })
      setModelIdEdits(prev => { const n = { ...prev }; delete n[modelId]; return n })

      const modelsResult = await getAllModels()
      setModels(modelsResult.models)
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      errorAlert.showError(t("error.saveFailed", { details: errorMessage }))
    }
  }

  // New model form handlers
  const addNewModelForm = () => {
    const newForm: EditableNewModel = {
      id: crypto.randomUUID(),
      data: {
        provider: selectedProvider || "",
        model_type: "llm",
        model_id: "",
        thinking: false,
        is_default: false,
        is_active: true,
      }
    }
    setNewModelForms(prev => [...prev, newForm])
  }

  const removeNewModelForm = (formId: string) => {
    setNewModelForms(prev => prev.filter(f => f.id !== formId))
  }

  const updateNewModelForm = (formId: string, updates: Partial<ModelCreate>) => {
    setNewModelForms(prev => prev.map(f =>
      f.id === formId ? { ...f, data: { ...f.data, ...updates } } : f
    ))
  }

  const updateNewModelType = (formId: string, modelType: ModelType) => {
    setNewModelForms(prev => prev.map(f =>
      f.id === formId ? { ...f, data: { ...f.data, model_type: modelType } } : f
    ))
  }

  // Batch save all new model forms
  const saveAllNewModels = async () => {
    // Filter out forms without model_id
    const validForms = newModelForms.filter(f => f.data.model_id?.trim())
    if (validForms.length === 0) return

    const saveOperations = validForms.map(form => {
      const fullModelId = form.data.model_id.includes("/")
        ? form.data.model_id
        : `${selectedProvider}/${form.data.model_id.trim()}`
      return createModel({
        ...form.data,
        model_id: fullModelId,
        provider: selectedProvider || "",
      })
    })

    try {
      await Promise.all(saveOperations)
      setNewModelForms([])

      const modelsResult = await getAllModels()
      setModels(modelsResult.models)
      if (selectedProvider) {
        setExpandedProviders(prev => new Set(prev).add(selectedProvider))
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      if (errorMessage.includes("model_id_exists")) {
        errorAlert.showError(t("error.modelIdExists"))
      } else {
        errorAlert.showError(t("error.createFailed", { details: errorMessage }))
      }
    }
  }

  const handleDeleteModel = async (model: ModelInfo) => {
    setDeletingModelIds(prev => new Set(prev).add(model.model_id))
    await new Promise(resolve => setTimeout(resolve, 300))

    try {
      await deleteModel(model.id)
      setModels(prev => prev.filter(m => m.id !== model.id))
      setPendingChanges(prev => { const n = { ...prev }; delete n[model.model_id]; return n })
    } catch (error) {
      console.error("Failed to delete model:", error)
      await loadData()
    } finally {
      setDeletingModelIds(prev => { const n = new Set(prev); n.delete(model.model_id); return n })
    }
  }

  const getEffectiveValue = (model: ModelInfo, field: keyof ModelChanges): unknown => {
    const changes = pendingChanges[model.model_id]
    return changes && changes[field] !== undefined ? changes[field] : model[field as keyof ModelInfo]
  }

  const toggleModelEdit = (modelId: string) => {
    setEditingModelIds(prev => {
      const n = new Set(prev)
      if (n.has(modelId)) n.delete(modelId)
      else n.add(modelId)
      return n
    })
  }

  const isEditingModel = (modelId: string): boolean => editingModelIds.has(modelId)

  const selectedProviderInfo = providers.find(p => p.provider === selectedProvider)
  const selectedProviderModels = models.filter(m => m.provider === selectedProvider)
  const hasNewModelForms = newModelForms.length > 0
  const validNewModelCount = newModelForms.filter(f => f.data.model_id?.trim()).length

  return (
    <>
      <ErrorAlertDialog state={errorAlert.state} onOpenChange={errorAlert.setOpen} />

      {/* Unsaved Changes Confirmation Dialog */}
      <Dialog open={!!pendingProviderSwitch} onOpenChange={() => setPendingProviderSwitch(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="size-5 text-amber-500" />
              {t("provider.unsavedChangesTitle") || "Unsaved Changes"}
            </DialogTitle>
            <DialogDescription>
              {t("provider.unsavedChangesMessage") || "You have unsaved changes. Are you sure you want to switch providers? Your changes will be lost."}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setPendingProviderSwitch(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (pendingProviderSwitch) {
                  if (selectedProvider) {
                    setProviderApiKeyEdits(prev => { const n = { ...prev }; delete n[selectedProvider]; return n })
                    setProviderBaseUrlEdits(prev => { const n = { ...prev }; delete n[selectedProvider]; return n })
                  }
                  setPendingProviderSwitch(null)
                  setTimeout(() => {
                    setSelectedProvider(pendingProviderSwitch)
                    toggleProviderExpand(pendingProviderSwitch)
                  }, 0)
                }
              }}
            >
              {t("common.discard") || "Discard"}
            </Button>
            <Button
              onClick={() => {
                if (pendingProviderSwitch && selectedProvider) {
                  void saveProviderConfig(selectedProvider).then(() => {
                    setPendingProviderSwitch(null)
                    setTimeout(() => {
                      setSelectedProvider(pendingProviderSwitch)
                      toggleProviderExpand(pendingProviderSwitch)
                    }, 0)
                  })
                }
              }}
            >
              {t("common.saveAndSwitch") || "Save & Switch"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent style={{ maxWidth: '95vw', width: '900px' }} className="dialog-scroll-area max-h-[85vh] overflow-y-auto
                                   bg-gradient-to-br from-background via-background to-muted/30
                                   dark:bg-gradient-to-br dark:from-[#0B0F1A] dark:via-[#111827] dark:to-[#1A2238]/50
                                   dark:border-primary/20 dark:backdrop-blur-xl
                                   shadow-2xl dark:shadow-[0_0_40px_rgba(0,209,255,0.1)]
                                   rounded-2xl p-0">
          <DialogHeader className="p-6 pb-4 border-b border-border/50">
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
                    <p>{t("provider.helpLink")}</p>
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
            <div className="flex h-[600px]">
              {/* Left Panel - Provider Tree */}
              <div className="w-72 border-r border-border/50 flex flex-col">
                <div className="p-4 border-b border-border/50">
                  <h4 className="font-semibold text-sm flex items-center gap-2">
                    <Server className="size-4 text-primary" />
                    {t("provider.title")}
                  </h4>
                </div>

                <div className="flex-1 overflow-y-auto p-3 space-y-1">
                  {providers.map((provider) => {
                    const isExpanded = expandedProviders.has(provider.provider)
                    const isSelected = selectedProvider === provider.provider
                    const providerModelCount = models.filter(m => m.provider === provider.provider).length

                    return (
                      <div key={provider.provider}>
                        <button
                          onClick={() => {
                            if (selectedProvider && hasUnsavedProviderChanges(selectedProvider) && selectedProvider !== provider.provider) {
                              setPendingProviderSwitch(provider.provider)
                              return
                            }
                            setSelectedProvider(provider.provider)
                            toggleProviderExpand(provider.provider)
                          }}
                          className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm transition-colors
                            ${isSelected
                              ? 'bg-primary/10 text-primary border border-primary/20'
                              : 'hover:bg-muted text-foreground'
                            }`}
                        >
                          {isExpanded ? (
                            <ChevronDown className="size-4 text-muted-foreground" />
                          ) : (
                            <ChevronRight className="size-4 text-muted-foreground" />
                          )}
                          <span className="font-medium flex-1 text-left">{provider.provider}</span>
                          <Badge variant="secondary" className="text-xs">{providerModelCount}</Badge>
                        </button>

                        {isExpanded && (
                          <div className="ml-4 mt-1 space-y-0.5">
                            {models
                              .filter(m => m.provider === provider.provider)
                              .sort((a, b) => getDisplayName(a.model_id).localeCompare(getDisplayName(b.model_id)))
                              .map(model => (
                                <div
                                  key={model.model_id}
                                  className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50"
                                >
                                  <span className="truncate">{getDisplayName(model.model_id)}</span>
                                  <Badge variant="outline" className="text-[10px] px-1 py-0">{model.model_type}</Badge>
                                  {model.is_default && (
                                    <Badge variant="secondary" className="text-[10px] px-1 py-0">{t("model.default")}</Badge>
                                  )}
                                </div>
                              ))}
                          </div>
                        )}
                      </div>
                    )
                  })}

                  {providers.length === 0 && (
                    <div className="text-center py-8 text-muted-foreground text-sm">
                      {t("provider.noProviders") || "No providers configured"}
                    </div>
                  )}
                </div>
              </div>

              {/* Right Panel - Provider/Model Configuration */}
              <div className="flex-1 flex flex-col overflow-hidden">
                {selectedProviderInfo ? (
                  <>
                    {/* Provider Config Section */}
                    <div className="p-5 border-b border-border/50 space-y-3">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 relative">
                          <Input
                            type={providerApiKeyVisible[selectedProviderInfo.provider] ? "text" : "password"}
                            placeholder={selectedProviderInfo.has_api_key ? "••••••••••••••••" : t("provider.apiKeyPlaceholder")}
                            value={providerApiKeyEdits[selectedProviderInfo.provider] || ""}
                            onChange={(e) => handleProviderApiKeyChange(selectedProviderInfo.provider, e.target.value)}
                            className="pr-10"
                          />
                          <button
                            type="button"
                            onClick={() => toggleProviderApiKeyVisible(selectedProviderInfo.provider)}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          >
                            {providerApiKeyVisible[selectedProviderInfo.provider] ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                          </button>
                        </div>
                        <Button
                          size="sm"
                          onClick={() => saveProviderConfig(selectedProviderInfo.provider)}
                          disabled={!providerApiKeyEdits[selectedProviderInfo.provider] && !providerBaseUrlEdits[selectedProviderInfo.provider]}
                          className="h-9 px-3"
                        >
                          {t("common.save")}
                        </Button>
                      </div>

                      {selectedProviderInfo.is_openai_compatible && (
                        <div>
                          <Input
                            placeholder={t("provider.baseUrlPlaceholder") || "http://localhost:11434/v1"}
                            value={providerBaseUrlEdits[selectedProviderInfo.provider] ?? selectedProviderInfo.base_url ?? ""}
                            onChange={(e) => handleProviderBaseUrlChange(selectedProviderInfo.provider, e.target.value)}
                          />
                        </div>
                      )}
                    </div>

                    {/* Models Section */}
                    <div className="flex-1 overflow-y-auto p-5">
                      <div className="flex items-center justify-between mb-4">
                        <h4 className="font-semibold text-sm text-muted-foreground tracking-wide">
                          {t("model.title")}
                        </h4>
                        <div className="flex items-center gap-2">
                          {hasNewModelForms ? (
                            <>
                              <Button
                                size="sm"
                                onClick={() => {
                                  // Save all pending changes for existing models first
                                  const saveChangeOperations = Object.keys(pendingChanges).map(modelId => saveChanges(modelId))
                                  void Promise.all(saveChangeOperations).then(() => {
                                    void saveAllNewModels()
                                  })
                                }}
                                disabled={validNewModelCount === 0 && Object.keys(pendingChanges).length === 0}
                              >
                                {t("common.save")} {validNewModelCount > 0 && `(${validNewModelCount})`}
                              </Button>
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={() => setNewModelForms([])}
                              >
                                {t("common.cancel")}
                              </Button>
                            </>
                          ) : (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={addNewModelForm}
                              className="gap-1"
                            >
                              <Plus className="size-3.5" />
                              {t("model.addModel")}
                            </Button>
                          )}
                        </div>
                      </div>

                      {/* New Model Forms List - Each is editable */}
                      {newModelForms.length > 0 && (
                        <div className="space-y-3 mb-4">
                          {newModelForms.map((form, index) => (
                            <div key={form.id} className="border border-primary/20 dark:border-primary/30 rounded-xl p-4 space-y-4 bg-gradient-to-br from-muted/50 to-muted/30">
                              <div className="flex items-center justify-between">
                                <span className="text-xs font-medium text-muted-foreground">{t("model.new")} #{index + 1}</span>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="size-7 rounded-lg text-destructive/60 hover:text-destructive"
                                  onClick={() => removeNewModelForm(form.id)}
                                >
                                  <Trash2 className="size-3.5" />
                                </Button>
                              </div>
                              <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-1.5">
                                  <label className="text-xs font-medium text-muted-foreground">{t("model.type")}</label>
                                  <Select
                                    value={form.data.model_type}
                                    onValueChange={(value: ModelType) => updateNewModelType(form.id, value)}
                                  >
                                    <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                                    <SelectContent>
                                      {MODEL_TYPES.map(type => <SelectItem key={type} value={type}>{type.toUpperCase()}</SelectItem>)}
                                    </SelectContent>
                                  </Select>
                                </div>
                                <div className="space-y-1.5">
                                  <label className="text-xs font-medium text-muted-foreground">Model ID</label>
                                  <Input
                                    placeholder="qwen3.5-27b"
                                    value={form.data.model_id}
                                    onChange={(e) => updateNewModelForm(form.id, { model_id: e.target.value })}
                                    className="h-8 text-xs"
                                  />
                                </div>
                              </div>
                              <div className="flex items-center gap-4 flex-wrap">
                                {form.data.model_type !== "embedding" && (
                                  <div className="flex items-center gap-2">
                                    <Switch
                                      id={`${form.id}-thinking`}
                                      checked={form.data.thinking}
                                      onCheckedChange={(checked) => updateNewModelForm(form.id, { thinking: checked })}
                                      className="scale-75"
                                    />
                                    <label htmlFor={`${form.id}-thinking`} className="text-xs">{t("model.thinking")}</label>
                                  </div>
                                )}
                                <div className="flex items-center gap-2">
                                  <Switch
                                    id={`${form.id}-active`}
                                    checked={form.data.is_active}
                                    onCheckedChange={(checked) => updateNewModelForm(form.id, { is_active: checked })}
                                    className="scale-75"
                                  />
                                  <label htmlFor={`${form.id}-active`} className="text-xs">{t("model.active")}</label>
                                </div>
                                <div className="flex items-center gap-2">
                                  <Switch
                                    id={`${form.id}-default`}
                                    checked={form.data.is_default}
                                    onCheckedChange={(checked) => updateNewModelForm(form.id, { is_default: checked })}
                                    className="scale-75"
                                  />
                                  <label htmlFor={`${form.id}-default`} className="text-xs">{t("model.default")}</label>
                                </div>
                              </div>
                              {form.data.model_type === "embedding" && (
                                <div className="flex items-start gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
                                  <AlertTriangle className="size-4 text-amber-500 mt-0.5 shrink-0" />
                                  <span className="text-xs text-amber-600 dark:text-amber-400">{t("model.embeddingWarning")}</span>
                                </div>
                              )}
                            </div>
                          ))}

                          {/* Add another model button */}
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={addNewModelForm}
                            className="w-full gap-1"
                          >
                            <Plus className="size-3.5" />
                            {t("model.continueAdd")}
                          </Button>
                        </div>
                      )}

                      {/* Models List */}
                      <div className="space-y-3">
                        {selectedProviderModels.length === 0 && newModelForms.length === 0 ? (
                          <div className="text-center py-8 text-muted-foreground text-sm border border-dashed border-border rounded-lg">
                            {t("model.noModelsForProvider") || "No models configured for this provider"}
                          </div>
                        ) : (
                          selectedProviderModels
                            .sort((a, b) => getDisplayName(a.model_id).localeCompare(getDisplayName(b.model_id)))
                            .map(model => {
                              const hasChanges = hasPendingChanges(model.model_id)
                              const effectiveThinking = getEffectiveValue(model, "thinking") as boolean
                              const effectiveActive = getEffectiveValue(model, "is_active") as boolean
                              const isDeleting = deletingModelIds.has(model.model_id)
                              const isEditing = isEditingModel(model.model_id)

                              return (
                                <div
                                  key={model.model_id}
                                  className="group border border-border/50 rounded-xl p-4 space-y-3 bg-card/50"
                                  style={{ opacity: isDeleting ? 0 : 1 }}
                                >
                                  <div className="flex items-center justify-between gap-3">
                                    <div className="flex items-center gap-2 flex-wrap">
                                      <span className="font-semibold">{getDisplayName(model.model_id)}</span>
                                      <Badge variant="outline" className="rounded-lg px-2 py-0.5 text-xs">{model.model_type.toUpperCase()}</Badge>
                                      {model.is_default && <Badge variant="secondary" className="rounded-lg px-2 py-0.5 text-xs">{t("model.default")}</Badge>}
                                    </div>
                                    <div className="flex items-center gap-1">
                                      {isEditing ? (
                                        <>
                                          <Button
                                            size="sm"
                                            className="h-8 px-3 transition-all hover:scale-105 active:scale-95"
                                            onClick={() => void saveChanges(model.model_id)}
                                            disabled={!hasChanges}
                                          >
                                            {t("common.save")}
                                          </Button>
                                          <Button
                                            variant="secondary"
                                            size="sm"
                                            className="h-8 px-3 transition-all hover:scale-105 active:scale-95"
                                            onClick={() => cancelChanges(model.model_id)}
                                          >
                                            {t("common.cancel")}
                                          </Button>
                                        </>
                                      ) : (
                                        <Button
                                          variant="ghost"
                                          size="icon"
                                          className="size-8 rounded-lg text-muted-foreground/60 hover:text-primary transition-all hover:scale-105 active:scale-95"
                                          onClick={() => toggleModelEdit(model.model_id)}
                                        >
                                          <Edit2 className="size-4" />
                                        </Button>
                                      )}
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        className="size-8 rounded-lg text-destructive/60 hover:text-destructive transition-all hover:scale-105 active:scale-95"
                                        onClick={() => void handleDeleteModel(model)}
                                      >
                                        <Trash2 className="size-4" />
                                      </Button>
                                    </div>
                                  </div>

                                  {/* Read-only switches when not editing */}
                                  {!isEditing ? (
                                    <div className="flex items-center gap-4 flex-wrap">
                                      {model.model_type !== "embedding" && (
                                        <div className="flex items-center gap-1.5">
                                          <Switch
                                            id={`thinking-${model.model_id}`}
                                            checked={model.thinking}
                                            disabled
                                            className="scale-75"
                                          />
                                          <label htmlFor={`thinking-${model.model_id}`} className="text-xs text-muted-foreground">
                                            {t("model.thinking")}
                                          </label>
                                        </div>
                                      )}
                                      <div className="flex items-center gap-1.5">
                                        <Switch
                                          id={`active-${model.model_id}`}
                                          checked={model.is_active}
                                          disabled
                                          className="scale-75"
                                        />
                                        <label htmlFor={`active-${model.model_id}`} className="text-xs text-muted-foreground">
                                          {t("model.active")}
                                        </label>
                                      </div>
                                      <div className="flex items-center gap-1.5">
                                        <Switch
                                          id={`default-${model.model_id}`}
                                          checked={model.is_default}
                                          disabled
                                          className="scale-75"
                                        />
                                        <label htmlFor={`default-${model.model_id}`} className="text-xs text-muted-foreground">
                                          {t("model.default")}
                                        </label>
                                      </div>
                                    </div>
                                  ) : (
                                    <>
                                      <div className="flex items-center gap-4 flex-wrap">
                                        {model.model_type !== "embedding" && (
                                          <div className="flex items-center gap-1.5">
                                            <Switch
                                              id={`thinking-${model.model_id}`}
                                              checked={effectiveThinking}
                                              onCheckedChange={(checked) => handleSwitchChange(model.model_id, "thinking", checked)}
                                              className="scale-75"
                                            />
                                            <label htmlFor={`thinking-${model.model_id}`} className="text-xs text-muted-foreground cursor-pointer">
                                              {t("model.thinking")}
                                            </label>
                                          </div>
                                        )}
                                        <div className="flex items-center gap-1.5">
                                          <Switch
                                            id={`active-${model.model_id}`}
                                            checked={effectiveActive}
                                            onCheckedChange={(checked) => handleSwitchChange(model.model_id, "is_active", checked)}
                                            className="scale-75"
                                          />
                                          <label htmlFor={`active-${model.model_id}`} className="text-xs text-muted-foreground cursor-pointer">
                                            {t("model.active")}
                                          </label>
                                        </div>
                                        <div className="flex items-center gap-1.5">
                                          <Switch
                                            id={`default-${model.model_id}`}
                                            checked={(pendingChanges[model.model_id]?.is_default ?? model.is_default)}
                                            onCheckedChange={(checked) => handleSwitchChange(model.model_id, "is_default", checked)}
                                            className="scale-75"
                                          />
                                          <label htmlFor={`default-${model.model_id}`} className="text-xs text-muted-foreground cursor-pointer">
                                            {t("model.default")}
                                          </label>
                                        </div>
                                      </div>

                                      {model.model_type === "embedding" && (
                                        <div className="flex items-start gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
                                          <AlertTriangle className="size-4 text-amber-500 mt-0.5 shrink-0" />
                                          <span className="text-xs text-amber-600 dark:text-amber-400">{t("model.embeddingWarning")}</span>
                                        </div>
                                      )}
                                      <div className="space-y-3 pt-2 border-t border-border/50 animate-in fade-in-0 slide-in-from-top-2 duration-200">
                                        <div className="grid grid-cols-2 gap-3">
                                          <div className="space-y-1.5">
                                            <label className="text-xs font-medium text-muted-foreground">Model ID</label>
                                            <Input
                                              placeholder=""
                                              value={modelIdEdits[model.model_id] ?? ""}
                                              onChange={(e) => handleModelIdChange(model.model_id, e.target.value)}
                                              className="h-8 text-xs"
                                            />
                                          </div>
                                          <div className="space-y-1.5">
                                            <label className="text-xs font-medium text-muted-foreground">{t("model.type")}</label>
                                            <Select
                                              value={modelTypeEdits[model.model_id] ?? model.model_type}
                                              onValueChange={(value: ModelType) => handleModelTypeChangeForEdit(model.model_id, value)}
                                            >
                                              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                                              <SelectContent>
                                                {MODEL_TYPES.map(type => <SelectItem key={type} value={type}>{type.toUpperCase()}</SelectItem>)}
                                              </SelectContent>
                                            </Select>
                                          </div>
                                        </div>
                                      </div>
                                    </>
                                  )}
                                </div>
                              )
                            })
                        )}
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="flex-1 flex items-center justify-center text-muted-foreground">
                    <div className="text-center space-y-2">
                      <Server className="size-12 mx-auto opacity-30" />
                      <p>{t("provider.selectProvider") || "Select a provider to configure"}</p>
                    </div>
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
