import { useState, useEffect, useCallback } from "react"
import { Eye, EyeOff, Plus, Trash2, Settings2, HelpCircle, Edit2, ChevronRight, ChevronDown, Server, AlertTriangle, RefreshCw } from "lucide-react"

import type { ModelInfo, ModelType, ModelCreate, ModelUpdate, ProviderInfo, ProviderUpdate, ProviderConnectionInfo, ProviderConnectionUpdate } from "@/types"
import { getAllModels, createModel, updateModel, deleteModel, setDefaultModel, getProviders, updateProvider, validateModel, getProviderConnections, createProviderConnection, updateProviderConnection, deleteProviderConnection } from "@/lib/api"
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
  onConfigChanged?: () => void | Promise<void>
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

export function ProviderConfigDialog({ open, onOpenChange, onConfigChanged }: ProviderConfigDialogProps) {
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
  const [providerNameEdits, setProviderNameEdits] = useState<Record<string, string>>({})
  const [providerEnabledEdits, setProviderEnabledEdits] = useState<Record<string, boolean>>({})
  const [providerApiKeyVisible, setProviderApiKeyVisible] = useState<Record<string, boolean>>({})
  const [deletingConnectionIds, setDeletingConnectionIds] = useState<Set<string>>(new Set())

  // New provider connection state
  const [isAddingConnection, setIsAddingConnection] = useState(false)
  const [newConnectionName, setNewConnectionName] = useState("")
  const [newConnectionBaseUrl, setNewConnectionBaseUrl] = useState("")
  const [newConnectionApiKey, setNewConnectionApiKey] = useState("")
  const [isCreatingConnection, setIsCreatingConnection] = useState(false)

  // Multiple editable new model forms
  const [newModelForms, setNewModelForms] = useState<EditableNewModel[]>([])

  const [modelIdEdits, setModelIdEdits] = useState<Record<string, string>>({})
  const [modelTypeEdits, setModelTypeEdits] = useState<Record<string, ModelType>>({})
  const [pendingChanges, setPendingChanges] = useState<Record<string, ModelChanges>>({})

  // Unsaved changes confirmation dialog state
  const [pendingProviderSwitch, setPendingProviderSwitch] = useState<string | null>(null)

  const errorAlert = useErrorAlert()

  const notifyConfigChanged = useCallback(async () => {
    await onConfigChanged?.()
  }, [onConfigChanged])

  // Check if current provider has unsaved changes
  const hasUnsavedProviderChanges = (provider: string): boolean => {
    if (providerApiKeyEdits[provider] !== undefined || providerBaseUrlEdits[provider] !== undefined) {
      return true
    }

    return connections
      .filter(connection => connection.provider_key === provider)
      .some(connection =>
        providerNameEdits[connection.connection_id] !== undefined ||
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
    setIsAddingConnection(false)
    setNewConnectionName("")
    setNewConnectionBaseUrl("")
    setNewConnectionApiKey("")
  }, [selectedProvider])

  useEffect(() => {
    if (open) {
      void loadData()
      setPendingChanges({})
      setNewModelForms([])
      setProviderNameEdits({})
      setIsAddingConnection(false)
      setNewConnectionName("")
      setNewConnectionBaseUrl("")
      setNewConnectionApiKey("")
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

  const handleProviderNameChange = (provider: string, value: string) => {
    setProviderNameEdits(prev => ({ ...prev, [provider]: value }))
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
        await notifyConfigChanged()
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error)
        errorAlert.showError(t("error.saveFailed", { details: errorMessage }))
      }
    }
  }

  const saveConnectionConfig = async (connectionId: string) => {
    const updateData: ProviderConnectionUpdate = {}
    const name = providerNameEdits[connectionId]
    const apiKey = providerApiKeyEdits[connectionId]
    const baseUrl = providerBaseUrlEdits[connectionId]
    const enabled = providerEnabledEdits[connectionId]

    if (name !== undefined && name.trim() !== "") {
      updateData.name = name.trim()
    }
    if (apiKey !== undefined && apiKey.trim() !== "") {
      updateData.api_key = apiKey
    }
    if (baseUrl !== undefined) {
      updateData.base_url = baseUrl.trim() || null
    }
    if (enabled !== undefined) {
      updateData.enabled = enabled
    }

    if (updateData.name || updateData.api_key || updateData.base_url !== undefined || updateData.enabled !== undefined) {
      try {
        await updateProviderConnection(connectionId, updateData)
        setProviderNameEdits(prev => { const n = { ...prev }; delete n[connectionId]; return n })
        setProviderApiKeyEdits(prev => { const n = { ...prev }; delete n[connectionId]; return n })
        setProviderBaseUrlEdits(prev => { const n = { ...prev }; delete n[connectionId]; return n })
        setProviderEnabledEdits(prev => { const n = { ...prev }; delete n[connectionId]; return n })
        const connectionsResult = await getProviderConnections()
        setConnections(connectionsResult.connections)
        await notifyConfigChanged()
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error)
        errorAlert.showError(t("error.saveFailed", { details: errorMessage }))
      }
    }
  }

  const startAddingConnection = () => {
    if (!selectedProvider) return
    const nextIndex = connections.filter(c => c.provider_key === selectedProvider).length + 1
    setNewConnectionName(selectedProvider === "openai-compatible" ? `Custom API ${nextIndex}` : `Connection ${nextIndex}`)
    setNewConnectionBaseUrl("")
    setNewConnectionApiKey("")
    setIsAddingConnection(true)
  }

  const cancelAddingConnection = () => {
    setIsAddingConnection(false)
    setNewConnectionName("")
    setNewConnectionBaseUrl("")
    setNewConnectionApiKey("")
  }

  const saveNewConnection = async () => {
    if (!selectedProvider) return
    const name = newConnectionName.trim()
    if (!name) return

    setIsCreatingConnection(true)
    try {
      const created = await createProviderConnection({
        provider_key: selectedProvider,
        name,
        preset_type: "custom",
        api_key: newConnectionApiKey.trim() || null,
        base_url: newConnectionBaseUrl.trim() || null,
        enabled: true,
      })
      const connectionsResult = await getProviderConnections()
      setConnections(connectionsResult.connections)
      setSelectedConnection(created.connection_id)
      setExpandedProviders(prev => new Set(prev).add(selectedProvider))
      cancelAddingConnection()
      await notifyConfigChanged()
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      errorAlert.showError(t("error.createFailed", { details: errorMessage }))
    } finally {
      setIsCreatingConnection(false)
    }
  }

  const handleDeleteConnection = async (connection: ProviderConnectionInfo) => {
    setDeletingConnectionIds(prev => new Set(prev).add(connection.connection_id))
    try {
      await deleteProviderConnection(connection.connection_id)
      const [modelsResult, connectionsResult, providersResult] = await Promise.all([
        getAllModels(),
        getProviderConnections(),
        getProviders(),
      ])
      setModels(modelsResult.models)
      setConnections(connectionsResult.connections)
      setProviders(providersResult.providers)
      setPendingChanges({})
      setNewModelForms([])

      const remainingConnections = connectionsResult.connections.filter(
        item => item.provider_key === connection.provider_key,
      )
      setSelectedConnection(remainingConnections[0]?.connection_id ?? null)
      await notifyConfigChanged()
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      errorAlert.showError(`删除自定义 API 失败：${errorMessage}`)
    } finally {
      setDeletingConnectionIds(prev => {
        const n = new Set(prev)
        n.delete(connection.connection_id)
        return n
      })
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
  const handleModelIdChange = (modelKey: string, value: string) => {
    setModelIdEdits(prev => ({ ...prev, [modelKey]: value }))
    setPendingChanges(prev => ({ ...prev, [modelKey]: { ...prev[modelKey], model_id: value } }))
  }

  const handleModelTypeChangeForEdit = (modelKey: string, value: ModelType) => {
    setModelTypeEdits(prev => ({ ...prev, [modelKey]: value }))
    setPendingChanges(prev => ({ ...prev, [modelKey]: { ...prev[modelKey], model_type: value } }))
  }

  const handleSwitchChange = (modelKey: string, field: keyof ModelChanges, value: boolean) => {
    setPendingChanges(prev => ({ ...prev, [modelKey]: { ...prev[modelKey], [field]: value } }))
  }

  const hasPendingChanges = (modelKey: string): boolean => {
    const changes = pendingChanges[modelKey]
    return changes ? Object.keys(changes).length > 0 : false
  }

  const cancelChanges = (modelKey: string) => {
    setPendingChanges(prev => { const n = { ...prev }; delete n[modelKey]; return n })
    setModelIdEdits(prev => { const n = { ...prev }; delete n[modelKey]; return n })
    setModelTypeEdits(prev => { const n = { ...prev }; delete n[modelKey]; return n })
    setEditingModelIds(prev => { const n = new Set(prev); n.delete(modelKey); return n })
  }

  const saveChanges = async (modelKey: string) => {
    const changes = pendingChanges[modelKey]
    if (!changes || Object.keys(changes).length === 0) return

    try {
      const model = models.find(m => m.id === modelKey)
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

      setPendingChanges(prev => { const n = { ...prev }; delete n[modelKey]; return n })
      setModelIdEdits(prev => { const n = { ...prev }; delete n[modelKey]; return n })
      setModelTypeEdits(prev => { const n = { ...prev }; delete n[modelKey]; return n })
      setEditingModelIds(prev => { const n = new Set(prev); n.delete(modelKey); return n })

      const modelsResult = await getAllModels()
      const connectionsResult = await getProviderConnections()
      setModels(modelsResult.models)
      setConnections(connectionsResult.connections)
      await notifyConfigChanged()
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
      await notifyConfigChanged()
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
    setDeletingModelIds(prev => new Set(prev).add(model.id))
    await new Promise(resolve => setTimeout(resolve, 300))

    try {
      await deleteModel(model.id)
      setModels(prev => prev.filter(m => m.id !== model.id))
      setPendingChanges(prev => { const n = { ...prev }; delete n[model.id]; return n })
      await notifyConfigChanged()
    } catch (error) {
      console.error("Failed to delete model:", error)
      await loadData()
    } finally {
      setDeletingModelIds(prev => { const n = new Set(prev); n.delete(model.id); return n })
    }
  }

  const toggleModelActive = async (model: ModelInfo, active: boolean) => {
    try {
      await updateModel(model.id, { is_active: active })
      setModels(prev => prev.map(m => m.id === model.id ? { ...m, is_active: active } : m))
      await notifyConfigChanged()
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error)
      errorAlert.showError(t("error.saveFailed", { details: errorMessage }))
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
    const probeKind = capability.probe_kind
      ?? (model.model_type === "embedding" ? "embedding" : "chat")
    const probeOk = capability.probe_ok ?? capability.chat_ok ?? false
    const embeddingDimensions = capability.embedding_dimensions ?? capability.dimensions
    const fieldPath = capability.reasoning_field_path ? ` · ${capability.reasoning_field_path}` : ""
    const errorCategory = capability.error_category
      ? ` · ${t("model.validationErrorCategory", { category: capability.error_category })}`
      : ""
    const errorText = capability.last_error ? ` · ${capability.last_error}` : ""
    const tooltip = `${t("model.validationLastChecked", { time: checkedAt })}${fieldPath}${errorCategory}${errorText}`

    if (probeKind === "embedding") {
      if (!probeOk) {
        return {
          label: t("model.validationEmbeddingFailed"),
          variant: "destructive",
          tooltip,
        }
      }
      return {
        label: embeddingDimensions
          ? t("model.validationEmbeddingOk", { dimensions: embeddingDimensions })
          : t("model.validationEmbeddingOkUnknownDimensions"),
        variant: "success",
        tooltip,
      }
    }

    if (!probeOk) {
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
    const changes = pendingChanges[model.id]
    return changes && changes[field] !== undefined ? changes[field] : model[field as keyof ModelInfo]
  }

  const toggleModelEdit = (model: ModelInfo) => {
    const modelKey = model.id
    if (editingModelIds.has(modelKey)) {
      setEditingModelIds(prev => { const n = new Set(prev); n.delete(modelKey); return n })
      return
    }
    setModelIdEdits(current => ({
      ...current,
      [modelKey]: current[modelKey] ?? model.provider_model_id ?? model.model_id,
    }))
    setEditingModelIds(prev => new Set(prev).add(modelKey))
  }

  const isEditingModel = (modelKey: string): boolean => editingModelIds.has(modelKey)

  const selectedProviderInfo = providers.find(p => getProviderKey(p) === selectedProvider)
  const selectedConnectionInfo = connections.find(c => c.connection_id === selectedConnection)
  const selectedConfigKey = selectedConnectionInfo?.connection_id || selectedProviderInfo?.provider || ""
  const hasSelectedConfigChanges = !!selectedConfigKey && (
    providerNameEdits[selectedConfigKey] !== undefined ||
    providerApiKeyEdits[selectedConfigKey] !== undefined ||
    providerBaseUrlEdits[selectedConfigKey] !== undefined ||
    providerEnabledEdits[selectedConfigKey] !== undefined
  )
  const selectedConnectionEnabled = selectedConnectionInfo
    ? (providerEnabledEdits[selectedConfigKey] ?? selectedConnectionInfo.enabled)
    : true
  const isCustomProvider = selectedProvider === "openai-compatible"
  const isDeletingSelectedConnection = selectedConnectionInfo
    ? deletingConnectionIds.has(selectedConnectionInfo.connection_id)
    : false
  const selectedConfigHasCredentials = isCustomProvider
    ? !!selectedConnectionInfo?.has_api_key
    : (selectedConnectionInfo?.has_api_key ?? selectedProviderInfo?.has_api_key ?? false)
  const selectedProviderModels = models.filter(m => {
    if (selectedConnection) return m.connection_id === selectedConnection
    if (isCustomProvider) return false
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
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">
                            {isCustomProvider ? "自定义 API" : (selectedConnectionInfo?.name || selectedProviderInfo.display_name || selectedProviderInfo.provider)}
                          </div>
                          <div className="truncate text-xs text-muted-foreground">
                            {isCustomProvider
                              ? "每条自定义 API 独立维护 URL、API Key 和模型列表"
                              : (selectedConnectionInfo ? selectedConnectionInfo.connection_id : selectedProviderInfo.provider)}
                          </div>
                        </div>
                        {isCustomProvider && (
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            className="shrink-0 gap-1"
                            onClick={startAddingConnection}
                            disabled={isAddingConnection || !selectedProvider}
                          >
                            <Plus className="size-3.5" />
                            添加自定义 API
                          </Button>
                        )}
                      </div>

                      {isCustomProvider && isAddingConnection && (
                        <div className="rounded-lg border border-border/60 bg-muted/30 p-3 space-y-3">
                          <div className="grid grid-cols-2 gap-3">
                            <Input
                              placeholder="名称，如 LongCat / 本地 vLLM"
                              value={newConnectionName}
                              onChange={(e) => setNewConnectionName(e.target.value)}
                              className="h-8 text-xs"
                            />
                            <Input
                              placeholder="Base URL，如 https://api.example.com/openai"
                              value={newConnectionBaseUrl}
                              onChange={(e) => setNewConnectionBaseUrl(e.target.value)}
                              className="h-8 text-xs"
                            />
                          </div>
                          <Input
                            type="password"
                            placeholder={t("provider.apiKeyPlaceholder")}
                            value={newConnectionApiKey}
                            onChange={(e) => setNewConnectionApiKey(e.target.value)}
                            className="h-8 text-xs"
                          />
                          <div className="flex justify-end gap-2">
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              onClick={cancelAddingConnection}
                              disabled={isCreatingConnection}
                            >
                              {t("common.cancel")}
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              onClick={() => void saveNewConnection()}
                              disabled={!newConnectionName.trim() || isCreatingConnection}
                            >
                              {isCreatingConnection ? "Saving..." : t("common.save")}
                            </Button>
                          </div>
                        </div>
                      )}

                      {isCustomProvider && selectedConnectionInfo && (
                        <div className="grid grid-cols-2 gap-3">
                          <Input
                            placeholder="自定义 API 名称"
                            value={providerNameEdits[selectedConfigKey] ?? selectedConnectionInfo.name}
                            onChange={(e) => handleProviderNameChange(selectedConfigKey, e.target.value)}
                            className="h-8 text-xs"
                          />
                          <Input
                            placeholder="Base URL"
                            value={providerBaseUrlEdits[selectedConfigKey] ?? selectedConnectionInfo.base_url ?? ""}
                            onChange={(e) => handleProviderBaseUrlChange(selectedConfigKey, e.target.value)}
                            className="h-8 text-xs"
                          />
                        </div>
                      )}

                      {(!isCustomProvider || selectedConnectionInfo) && (
                      <div className="flex items-center gap-2">
                        <div className="flex-1 relative">
                          <Input
                            type={providerApiKeyVisible[selectedConfigKey] ? "text" : "password"}
                            placeholder={isCustomProvider && selectedConfigHasCredentials ? "API Key saved" : (selectedConfigHasCredentials ? "••••••••••••••••" : t("provider.apiKeyPlaceholder"))}
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
                        {isCustomProvider && selectedConnectionInfo && (
                          <Button
                            type="button"
                            variant="destructive"
                            size="sm"
                            onClick={() => void handleDeleteConnection(selectedConnectionInfo)}
                            disabled={isDeletingSelectedConnection}
                            className="h-9 px-3"
                          >
                            {isDeletingSelectedConnection ? "Deleting..." : "删除"}
                          </Button>
                        )}
                      </div>
                      )}

                      {isCustomProvider && !selectedConnectionInfo && (
                        <div className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-muted-foreground">
                          先添加一条自定义 API，再为它添加模型。
                        </div>
                      )}

                      {selectedConnectionInfo && !isCustomProvider && (
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
                                    disabled={!selectedConfigHasCredentials}
                                  >
                                    <Plus className="size-3.5" />
                                    {t("model.addModel")}
                                  </Button>
                                </TooltipTrigger>
                                {!selectedConfigHasCredentials && (
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
                                  disabled={!selectedConfigHasCredentials}
                                >
                                  <Plus className="size-3.5" />
                                  {t("model.continueAdd")}
                                </Button>
                              </TooltipTrigger>
                              {!selectedConfigHasCredentials && (
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
                            {!selectedConfigHasCredentials
                              ? (t("model.needApiKeyFirstThenAdd"))
                              : (t("model.noModelsForProvider") || "No models configured for this provider")
                            }
                          </div>
                        ) : (
                          selectedProviderModels
                            .sort((a, b) => getDisplayName(a.model_id).localeCompare(getDisplayName(b.model_id)))
                            .map(model => {
                              const modelKey = model.id
                              const hasChanges = hasPendingChanges(modelKey)
                              const effectiveThinking = getEffectiveValue(model, "thinking") as boolean
                              const effectiveActive = getEffectiveValue(model, "is_active") as boolean
                              const isDeleting = deletingModelIds.has(modelKey)
                              const isEditing = isEditingModel(modelKey)
                              const isValidating = validatingModelIds.has(model.id)
                              const capabilityStatus = getCapabilityStatus(model)

                              return (
                                <div
                                  key={modelKey}
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
                                              disabled={isValidating || !selectedConfigHasCredentials}
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
                                            onClick={() => void saveChanges(modelKey)}
                                            disabled={!hasChanges}
                                          >
                                            {t("common.save")}
                                          </Button>
                                          <Button
                                            variant="secondary"
                                            size="sm"
                                            className="h-8 px-3 transition-all hover:scale-105 active:scale-95"
                                            onClick={() => cancelChanges(modelKey)}
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
                                                onClick={() => toggleModelEdit(model)}
                                                disabled={!selectedConfigHasCredentials}
                                              >
                                                <Edit2 className="size-4" />
                                              </Button>
                                            </TooltipTrigger>
                                            {!selectedConfigHasCredentials && (
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
                                            id={`thinking-${modelKey}`}
                                            checked={model.thinking}
                                            disabled
                                            className="scale-75"
                                          />
                                          <label htmlFor={`thinking-${modelKey}`} className="text-xs text-muted-foreground">
                                            {t("model.thinking")}
                                          </label>
                                        </div>
                                      )}
                                      <div className="flex items-center gap-1.5">
                                        <Switch
                                          id={`active-${modelKey}`}
                                          checked={model.is_active}
                                          onCheckedChange={(checked) => void toggleModelActive(model, checked)}
                                          className="scale-75"
                                        />
                                        <label htmlFor={`active-${modelKey}`} className="text-xs text-muted-foreground">
                                          {t("model.active")}
                                        </label>
                                      </div>
                                      <div className="flex items-center gap-1.5">
                                        <Switch
                                          id={`default-${modelKey}`}
                                          checked={model.is_default}
                                          disabled
                                          className="scale-75"
                                        />
                                        <label htmlFor={`default-${modelKey}`} className="text-xs text-muted-foreground">
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
                                              id={`thinking-${modelKey}`}
                                              checked={effectiveThinking}
                                              onCheckedChange={(checked) => handleSwitchChange(modelKey, "thinking", checked)}
                                              className="scale-75"
                                            />
                                            <label htmlFor={`thinking-${modelKey}`} className="text-xs text-muted-foreground cursor-pointer">
                                              {t("model.thinking")}
                                            </label>
                                          </div>
                                        )}
                                        <div className="flex items-center gap-1.5">
                                          <Switch
                                            id={`active-${modelKey}`}
                                            checked={effectiveActive}
                                            onCheckedChange={(checked) => handleSwitchChange(modelKey, "is_active", checked)}
                                            className="scale-75"
                                          />
                                          <label htmlFor={`active-${modelKey}`} className="text-xs text-muted-foreground cursor-pointer">
                                            {t("model.active")}
                                          </label>
                                        </div>
                                        <div className="flex items-center gap-1.5">
                                          <Switch
                                            id={`default-${modelKey}`}
                                            checked={(pendingChanges[modelKey]?.is_default ?? model.is_default)}
                                            onCheckedChange={(checked) => handleSwitchChange(modelKey, "is_default", checked)}
                                            className="scale-75"
                                          />
                                          <label htmlFor={`default-${modelKey}`} className="text-xs text-muted-foreground cursor-pointer">
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
                                              value={modelIdEdits[modelKey] ?? model.provider_model_id ?? model.model_id}
                                              onChange={(e) => handleModelIdChange(modelKey, e.target.value)}
                                              className="h-8 text-xs"
                                            />
                                          </div>
                                          <div className="space-y-1.5">
                                            <label className="text-xs font-medium text-muted-foreground">{t("model.type")}</label>
                                            <Select
                                              value={modelTypeEdits[modelKey] ?? model.model_type}
                                              onValueChange={(value: ModelType) => handleModelTypeChangeForEdit(modelKey, value)}
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
