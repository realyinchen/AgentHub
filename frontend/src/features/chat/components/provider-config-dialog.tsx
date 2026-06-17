import { useState, useEffect, useCallback } from "react"
import { Eye, EyeOff, Plus, Trash2, Settings2, HelpCircle, Edit2, ChevronRight, ChevronDown, Server, AlertTriangle, RefreshCw } from "lucide-react"

import type { ModelInfo, ModelType, ModelCreate, ModelUpdate, ProviderInfo, ProviderUpdate, ProviderConnectionInfo, ProviderConnectionUpdate } from "@/types"
import { getAllModels, createModel, updateModel, deleteModel, setDefaultModel, getProviders, updateProvider, validateModel, getProviderConnections, updateProviderConnection } from "@/lib/api"
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

type CapabilityBadgeVariant = "default" | "secondary" | "destructive" | "outline" | "ghost" | "link" | "warm" | "success"

// Editable new model form with unique id
type EditableNewModel = {
  id: string
  data: ModelCreate
}

const getDisplayName = (modelId: string): string => {
  return modelId.split("/").pop() || modelId
}

const getProviderKey = (provider: ProviderInfo): string => provider.provider_key || provider.provider

const getModelProviderKey = (model: ModelInfo): string => model.provider_key || model.provider

export function ProviderConfigDialog({ open, onOpenChange }: ProviderConfigDialogProps) {
  const { t } = useI18n()
  const [models, setModels] = useState<ModelInfo[]>([])
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [connections, setConnections] = useState<ProviderConnectionInfo[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [selectedConnection, setSelectedConnection] = useState<string | null>(null)
  const [expandedProviders, setExpandedProviders] = useState<Set<string>>(new Set())
  const [deletingModelIds, setDeletingModelIds] = useState<Set<string>>(new Set())
  const [editingModelIds, setEditingModelIds] = useState<Set<string>>(new Set())
  const [validatingModelIds, setValidatingModelIds] = useState<Set<string>>(new Set())

  // Provider editing state
  const [providerApiKeyEdits, setProviderApiKeyEdits] = useState<Record<string, string>>({})
  const [providerBaseUrlEdits, setProviderBaseUrlEdits] = useState<Record<string, string>>({})
  const [providerEnabledEdits, setProviderEnabledEdits] = useState<Record<string, boolean>>({})
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
    if (providerApiKeyEdits[provider] !== undefined || providerBaseUrlEdits[provider] !== undefined) {
      return true
    }

    return connections
      .filter(connection => connection.provider_key === provider)
      .some(connection =>
        providerApiKeyEdits[connection.connection_id] !== undefined ||
        providerBaseUrlEdits[connection.connection_id] !== undefined ||
        providerEnabledEdits[connection.connection_id] !== undefined
      )
  }

  const loadData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [modelsResult, providersResult, connectionsResult] = await Promise.all([
        getAllModels(),
        getProviders(),
        getProviderConnections(),
      ])
      setModels(modelsResult.models)
      setProviders(providersResult.providers)
      setConnections(connectionsResult.connections)
    } catch (error) {
      console.error("Failed to load data:", error)
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Auto-select first provider when data is loaded and no provider is selected
  useEffect(() => {
    if (providers.length > 0 && !selectedProvider) {
      setSelectedProvider(getProviderKey(providers[0]))
    }
  }, [providers, selectedProvider])

  useEffect(() => {
    if (!selectedProvider) {
      setSelectedConnection(null)
      return
    }
    const providerConnections = connections.filter(c => c.provider_key === selectedProvider)
    if (providerConnections.length === 0) {
      setSelectedConnection(null)
      return
    }
    if (!selectedConnection || !providerConnections.some(c => c.connection_id === selectedConnection)) {
      setSelectedConnection(providerConnections[0].connection_id)
    }
  }, [connections, selectedProvider, selectedConnection])

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

  const handleProviderEnabledChange = (provider: string, value: boolean) => {
    setProviderEnabledEdits(prev => ({ ...prev, [provider]: value }))
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

  const saveConnectionConfig = async (connectionId: string) => {
    const updateData: ProviderConnectionUpdate = {}
    const apiKey = providerApiKeyEdits[connectionId]
    const baseUrl = providerBaseUrlEdits[connectionId]
    const enabled = providerEnabledEdits[connectionId]

    if (apiKey !== undefined && apiKey.trim() !== "") {
      updateData.api_key = apiKey
    }
    if (baseUrl !== undefined) {
      updateData.base_url = baseUrl.trim() || null
    }
    if (enabled !== undefined) {
      updateData.enabled = enabled
    }

    if (updateData.api_key || updateData.base_url !== undefined || updateData.enabled !== undefined) {
      try {
        await updateProviderConnection(connectionId, updateData)
        setProviderApiKeyEdits(prev => { const n = { ...prev }; delete n[connectionId]; return n })
        setProviderBaseUrlEdits(prev => { const n = { ...prev }; delete n[connectionId]; return n })
        setProviderEnabledEdits(prev => { const n = { ...prev }; delete n[connectionId]; return n })
        const connectionsResult = await getProviderConnections()
        setConnections(connectionsResult.connections)
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error)
        errorAlert.showError(t("error.saveFailed", { details: errorMessage }))
      }
    }
  }

  const saveCurrentProviderConfig = async () => {
    if (selectedConnection) {
      await saveConnectionConfig(selectedConnection)
      return
    }
    if (selectedProvider) {
      await saveProviderConfig(selectedProvider)
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
        updateData.model_id = newModelId
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
      setModelTypeEdits(prev => { const n = { ...prev }; delete n[modelId]; return n })
      setEditingModelIds(prev => { const n = new Set(prev); n.delete(modelId); return n })

      const modelsResult = await getAllModels()
      const connectionsResult = await getProviderConnections()
      setModels(modelsResult.models)
      setConnections(connectionsResult.connections)
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
        connection_id: selectedConnection,
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
      return createModel({
        ...form.data,
        model_id: form.data.model_id.trim(),
        provider: selectedProvider || "",
        connection_id: selectedConnection,
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

  const handleValidateModel = async (model: ModelInfo) => {
    setValidatingModelIds(prev => new Set(prev).add(model.id))
    try {
      await validateModel(model.id, model.model_type !== "embedding")
      await loadData()
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      errorAlert.showError(t("model.validationError", { details: errorMessage }))
    } finally {
      setValidatingModelIds(prev => { const n = new Set(prev); n.delete(model.id); return n })
    }
  }

  const getCapabilityStatus = (model: ModelInfo): {
    label: string
    variant: CapabilityBadgeVariant
    tooltip: string
  } => {
    const capability = model.capability
    if (!capability) {
      return {
        label: t("model.validationUnchecked"),
        variant: "outline",
        tooltip: t("model.validationNoStatus"),
      }
    }

    const checkedAt = new Date(capability.checked_at).toLocaleString()
    const fieldPath = capability.reasoning_field_path ? ` · ${capability.reasoning_field_path}` : ""
    const errorText = capability.last_error ? ` · ${capability.last_error}` : ""
    const tooltip = `${t("model.validationLastChecked", { time: checkedAt })}${fieldPath}${errorText}`

    if (!capability.chat_ok) {
      return { label: t("model.validationFailed"), variant: "destructive", tooltip }
    }
    if (capability.thinking_request_ok && capability.reasoning_text_ok) {
      return { label: t("model.validationThinkingVerified"), variant: "success", tooltip }
    }
    if (capability.thinking_request_ok && capability.reasoning_text_ok === false) {
      return { label: t("model.validationThinkingNoText"), variant: "warm", tooltip }
    }
    if (capability.thinking_request_ok === false) {
      return { label: t("model.validationChatOnly"), variant: "secondary", tooltip }
    }
    return { label: t("model.validationChatOk"), variant: "secondary", tooltip }
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

  const selectedProviderInfo = providers.find(p => getProviderKey(p) === selectedProvider)
  const selectedConnectionInfo = connections.find(c => c.connection_id === selectedConnection)
  const selectedConfigKey = selectedConnectionInfo?.connection_id || selectedProviderInfo?.provider || ""
  const hasSelectedConfigChanges = !!selectedConfigKey && (
    providerApiKeyEdits[selectedConfigKey] !== undefined ||
    providerBaseUrlEdits[selectedConfigKey] !== undefined ||
    providerEnabledEdits[selectedConfigKey] !== undefined
  )
  const selectedConnectionEnabled = selectedConnectionInfo
    ? (providerEnabledEdits[selectedConfigKey] ?? selectedConnectionInfo.enabled)
    : true
  const selectedProviderModels = models.filter(m => {
    if (selectedConnection) return m.connection_id === selectedConnection
    return getModelProviderKey(m) === selectedProvider
  })
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
                    setProviderEnabledEdits(prev => {
                      const n = { ...prev }
                      connections
                        .filter(connection => connection.provider_key === selectedProvider)
                        .forEach(connection => { delete n[connection.connection_id] })
                      return n
                    })
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
                if (pendingProviderSwitch) {
                  void saveCurrentProviderConfig().then(() => {
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
                    const providerKey = getProviderKey(provider)
                    const providerConnections = connections.filter(c => c.provider_key === providerKey)
                    const isExpanded = expandedProviders.has(providerKey)
                    const isSelected = selectedProvider === providerKey
                    const providerModelCount = provider.model_count ?? models.filter(m => getModelProviderKey(m) === providerKey).length

                    return (
                      <div key={providerKey}>
                        <button
                          onClick={() => {
                            if (selectedProvider && hasUnsavedProviderChanges(selectedProvider) && selectedProvider !== providerKey) {
                              setPendingProviderSwitch(providerKey)
                              return
                            }
                            setSelectedProvider(providerKey)
                            setSelectedConnection(providerConnections[0]?.connection_id || null)
                            toggleProviderExpand(providerKey)
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
                          <span className="font-medium flex-1 text-left">{provider.display_name || providerKey}</span>
                          <Badge variant="secondary" className="text-xs">{providerModelCount}</Badge>
                        </button>

                        {isExpanded && (
                          <div className="ml-4 mt-1 space-y-0.5">
                            {providerConnections
                              .sort((a, b) => a.name.localeCompare(b.name))
                              .map(connection => (
                                <button
                                  key={connection.connection_id}
                                  onClick={() => {
                                    setSelectedProvider(providerKey)
                                    setSelectedConnection(connection.connection_id)
                                  }}
                                  className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-md text-xs text-left transition-colors
                                    ${selectedConnection === connection.connection_id
                                      ? 'bg-primary/10 text-primary'
                                      : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
                                    }`}
                                >
                                  <span className="truncate flex-1">{connection.name}</span>
                                  {!connection.enabled && (
                                    <Badge variant="secondary" className="text-[10px] px-1 py-0">
                                      {t("provider.disabled")}
                                    </Badge>
                                  )}
                                  <Badge variant={connection.enabled ? "outline" : "secondary"} className="text-[10px] px-1 py-0">
                                    {connection.model_count}
                                  </Badge>
                                </button>
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
                            type={providerApiKeyVisible[selectedConfigKey] ? "text" : "password"}
                            placeholder={(selectedConnectionInfo?.has_api_key ?? selectedProviderInfo.has_api_key) ? "••••••••••••••••" : t("provider.apiKeyPlaceholder")}
                            value={providerApiKeyEdits[selectedConfigKey] || ""}
                            onChange={(e) => handleProviderApiKeyChange(selectedConfigKey, e.target.value)}
                            className="pr-10"
                          />
                          <button
                            type="button"
                            onClick={() => toggleProviderApiKeyVisible(selectedConfigKey)}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          >
                            {providerApiKeyVisible[selectedConfigKey] ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                          </button>
                        </div>
                        <Button
                          size="sm"
                          onClick={() => selectedConnectionInfo ? void saveConnectionConfig(selectedConnectionInfo.connection_id) : void saveProviderConfig(selectedProviderInfo.provider)}
                          disabled={!hasSelectedConfigChanges}
                          className="h-9 px-3"
                        >
                          {t("common.save")}
                        </Button>
                      </div>

                      {selectedConnectionInfo && (
                        <div>
                          <Input
                            placeholder={t("provider.baseUrlPlaceholder") || "http://localhost:11434/v1"}
                            value={providerBaseUrlEdits[selectedConfigKey] ?? selectedConnectionInfo?.base_url ?? selectedProviderInfo.base_url ?? ""}
                            onChange={(e) => handleProviderBaseUrlChange(selectedConfigKey, e.target.value)}
                          />
                        </div>
                      )}

                      {selectedConnectionInfo && (
                        <div className="flex items-center justify-between gap-4 rounded-lg border border-border/60 bg-muted/30 px-4 py-3">
                          <div className="min-w-0">
                            <label htmlFor={`connection-enabled-${selectedConnectionInfo.connection_id}`} className="text-sm font-medium">
                              {t("provider.enabled")}
                            </label>
                            <p className="text-xs text-muted-foreground">
                              {t("provider.enabledDescription")}
                            </p>
                          </div>
                          <Switch
                            id={`connection-enabled-${selectedConnectionInfo.connection_id}`}
                            checked={selectedConnectionEnabled}
                            onCheckedChange={(checked) => handleProviderEnabledChange(selectedConnectionInfo.connection_id, checked)}
                            className="shrink-0"
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
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    onClick={addNewModelForm}
                                    className="gap-1"
                                    disabled={!(selectedConnectionInfo?.has_api_key ?? selectedProviderInfo.has_api_key)}
                                  >
                                    <Plus className="size-3.5" />
                                    {t("model.addModel")}
                                  </Button>
                                </TooltipTrigger>
                                {!(selectedConnectionInfo?.has_api_key ?? selectedProviderInfo.has_api_key) && (
                                  <TooltipContent side="top" className="max-w-xs">
                                    <p>{t("model.needApiKeyFirst")}</p>
                                  </TooltipContent>
                                )}
                              </Tooltip>
                            </TooltipProvider>
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
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  onClick={addNewModelForm}
                                  className="w-full gap-1"
                                  disabled={!(selectedConnectionInfo?.has_api_key ?? selectedProviderInfo.has_api_key)}
                                >
                                  <Plus className="size-3.5" />
                                  {t("model.continueAdd")}
                                </Button>
                              </TooltipTrigger>
                              {!(selectedConnectionInfo?.has_api_key ?? selectedProviderInfo.has_api_key) && (
                                <TooltipContent side="top" className="max-w-xs">
                                  <p>{t("model.needApiKeyFirst")}</p>
                                </TooltipContent>
                              )}
                            </Tooltip>
                          </TooltipProvider>
                        </div>
                      )}

                      {/* Models List */}
                      <div className="space-y-3">
                        {selectedProviderModels.length === 0 && newModelForms.length === 0 ? (
                          <div className="text-center py-8 text-muted-foreground text-sm border border-dashed border-border rounded-lg">
                            {!(selectedConnectionInfo?.has_api_key ?? selectedProviderInfo.has_api_key)
                              ? (t("model.needApiKeyFirstThenAdd"))
                              : (t("model.noModelsForProvider") || "No models configured for this provider")
                            }
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
                              const isValidating = validatingModelIds.has(model.id)
                              const capabilityStatus = getCapabilityStatus(model)

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
                                      <TooltipProvider>
                                        <Tooltip>
                                          <TooltipTrigger asChild>
                                            <Badge variant={capabilityStatus.variant} className="rounded-lg px-2 py-0.5 text-xs">
                                              {capabilityStatus.label}
                                            </Badge>
                                          </TooltipTrigger>
                                          <TooltipContent side="top" className="max-w-sm">
                                            <p>{capabilityStatus.tooltip}</p>
                                          </TooltipContent>
                                        </Tooltip>
                                      </TooltipProvider>
                                    </div>
                                    <div className="flex items-center gap-1">
                                      <TooltipProvider>
                                        <Tooltip>
                                          <TooltipTrigger asChild>
                                            <Button
                                              variant="ghost"
                                              size="icon"
                                              className="size-8 rounded-lg text-muted-foreground/60 hover:text-primary transition-all hover:scale-105 active:scale-95"
                                              onClick={() => void handleValidateModel(model)}
                                              disabled={isValidating || !(selectedConnectionInfo?.has_api_key ?? selectedProviderInfo.has_api_key)}
                                            >
                                              <RefreshCw className={`size-4 ${isValidating ? "animate-spin" : ""}`} />
                                            </Button>
                                          </TooltipTrigger>
                                          <TooltipContent side="top" className="max-w-xs">
                                            <p>{isValidating ? t("model.validating") : t("model.validate")}</p>
                                          </TooltipContent>
                                        </Tooltip>
                                      </TooltipProvider>
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
                                        <TooltipProvider>
                                          <Tooltip>
                                            <TooltipTrigger asChild>
                                              <Button
                                                variant="ghost"
                                                size="icon"
                                                className="size-8 rounded-lg text-muted-foreground/60 hover:text-primary transition-all hover:scale-105 active:scale-95"
                                                onClick={() => toggleModelEdit(model.model_id)}
                                                disabled={!(selectedConnectionInfo?.has_api_key ?? selectedProviderInfo.has_api_key)}
                                              >
                                                <Edit2 className="size-4" />
                                              </Button>
                                            </TooltipTrigger>
                                            {!(selectedConnectionInfo?.has_api_key ?? selectedProviderInfo.has_api_key) && (
                                              <TooltipContent side="top" className="max-w-xs">
                                                <p>{t("model.needApiKeyFirst")}</p>
                                              </TooltipContent>
                                            )}
                                          </Tooltip>
                                        </TooltipProvider>
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
