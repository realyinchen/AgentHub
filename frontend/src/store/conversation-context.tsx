import React, { createContext, useContext, useCallback, useState } from "react"
import type { MessageNode, MessageNodeCreate } from "@/types/message-tree"
import { MessageTreeManager, getMessageTreeManager, resetMessageTreeManager } from "@/store/message-tree"
import {
  getMessageTree as fetchMessageTree,
  createMessageNode,
  updateMessageNode,
  updateCurrentLeaf,
  streamChat,
} from "@/lib/api"
import type { StreamEvent, UserInput } from "@/types"

// Types
export interface ConversationState {
  threadId: string | null
  agentId: string
  thinkingMode: boolean
  isLoading: boolean
  isStreaming: boolean
  isLocked: boolean // For share links
  lockedLeafId: string | null // For share links
  currentPath: MessageNode[]
}

export interface ConversationActions {
  // Tree management
  loadTree: (threadId: string, leafId?: string) => Promise<void>
  clearTree: () => void
  
  // Message operations
  sendMessage: (content: string) => Promise<void>
  retry: (nodeId: string) => Promise<void>
  quote: (nodeId: string, newContent: string) => Promise<void>
  editUserMessage: (nodeId: string, newContent: string) => Promise<void>
  
  // Branch navigation
  switchBranch: (nodeId: string) => Promise<void>
  
  // State updates
  setAgentId: (agentId: string) => void
  setThinkingMode: (enabled: boolean) => void
  
  // Tree access
  getTreeManager: () => MessageTreeManager
}

export type ConversationContextType = ConversationState & ConversationActions

// Context
const ConversationContext = createContext<ConversationContextType | null>(null)

// Provider
export function ConversationProvider({ children }: { children: React.ReactNode }) {
  const [threadId, setThreadId] = useState<string | null>(null)
  const [agentId, setAgentId] = useState<string>("chatbot")
  const [thinkingMode, setThinkingMode] = useState<boolean>(false)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [isStreaming, setIsStreaming] = useState<boolean>(false)
  const [isLocked, setIsLocked] = useState<boolean>(false)
  const [lockedLeafId, setLockedLeafId] = useState<string | null>(null)
  const [currentPath, setCurrentPath] = useState<MessageNode[]>([])
  const [, setAbortController] = useState<AbortController | null>(null)
  
  const treeManager = getMessageTreeManager()

  // Update current path whenever tree changes
  const updateCurrentPath = useCallback(() => {
    setCurrentPath(treeManager.getCurrentPath())
  }, [treeManager])

  // Load tree from server
  const loadTree = useCallback(async (newThreadId: string, leafId?: string) => {
    setIsLoading(true)
    try {
      const tree = await fetchMessageTree(newThreadId, leafId)
      treeManager.loadFromTree(tree)
      setThreadId(newThreadId)
      
      if (leafId) {
        setIsLocked(true)
        setLockedLeafId(leafId)
      } else {
        setIsLocked(false)
        setLockedLeafId(null)
      }
      
      updateCurrentPath()
    } catch (error) {
      console.error("Failed to load message tree:", error)
    } finally {
      setIsLoading(false)
    }
  }, [treeManager, updateCurrentPath])

  // Clear tree
  const clearTree = useCallback(() => {
    resetMessageTreeManager()
    setThreadId(null)
    setIsLocked(false)
    setLockedLeafId(null)
    setCurrentPath([])
  }, [])

  // Send message
  const sendMessage = useCallback(async (content: string) => {
    if (isLocked || isStreaming) return
    
    // Create user message node
    const userNodeData = treeManager.createNewUserMessage(content)
    const userNode = await createMessageNode(userNodeData)
    treeManager.addNode(userNode)
    treeManager.setCurrentLeafId(userNode.id)
    
    // Update current path to show user message
    updateCurrentPath()
    
    // Create assistant message node (empty, will be filled by streaming)
    const assistantNodeData = treeManager.createNewAssistantMessage(userNode.id)
    const assistantNode = await createMessageNode(assistantNodeData)
    treeManager.addNode(assistantNode)
    treeManager.setCurrentLeafId(assistantNode.id)
    
    // Update current path to show empty assistant message
    updateCurrentPath()
    
    // Update current_leaf_id on server
    await updateCurrentLeaf(treeManager.getThreadId()!, assistantNode.id)
    
    // Start streaming
    setIsStreaming(true)
    const controller = new AbortController()
    setAbortController(controller)
    
    const input: UserInput = {
      content,
      agent_id: agentId,
      thread_id: treeManager.getThreadId(),
      thinking_mode: thinkingMode,
    }
    
    let streamedContent = ""
    
    try {
      await streamChat(
        input,
        (event: StreamEvent) => {
          if (event.type === "token") {
            streamedContent += event.content
            treeManager.updateNodeContent(assistantNode.id, streamedContent)
            updateCurrentPath()
          } else if (event.type === "message") {
            // Final message, update with full content
            treeManager.updateNodeContent(assistantNode.id, event.content.content)
            updateCurrentPath()
          }
        },
        controller.signal,
      )
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        console.error("Streaming error:", error)
      }
    } finally {
      setIsStreaming(false)
      setAbortController(null)
      
      // Update the node on server with final content
      const finalNode = treeManager.getNode(assistantNode.id)
      if (finalNode) {
        await updateMessageNode(assistantNode.id, { content: finalNode.content })
      }
    }
  }, [treeManager, agentId, thinkingMode, isLocked, isStreaming, updateCurrentPath])

  // Retry (regenerate assistant message)
  const retry = useCallback(async (nodeId: string) => {
    if (isLocked || isStreaming) return
    
    const node = treeManager.getNode(nodeId)
    if (!node || node.role !== "assistant") return
    
    // Get the parent (user message) to use as context
    const parentNode = node.parent_id ? treeManager.getNode(node.parent_id) : null
    if (!parentNode || parentNode.role !== "user") return
    
    // Create a new assistant node as sibling
    const newBranchIndex = treeManager.getNextBranchIndex(node.parent_id)
    const assistantNodeData: MessageNodeCreate = {
      thread_id: treeManager.getThreadId()!,
      role: "assistant",
      content: "",
      parent_id: node.parent_id,
      branch_index: newBranchIndex,
    }
    const assistantNode = await createMessageNode(assistantNodeData)
    treeManager.addNode(assistantNode)
    treeManager.setCurrentLeafId(assistantNode.id)
    updateCurrentPath()
    
    // Update current_leaf_id on server
    await updateCurrentLeaf(treeManager.getThreadId()!, assistantNode.id)
    
    // Start streaming with the parent user message as context
    setIsStreaming(true)
    const controller = new AbortController()
    setAbortController(controller)
    
    // Get the path up to the parent node for context
    // const pathToParent = treeManager.getPathToNode(parentNode.id)
    // const messages = pathToParent.map(n => ({ role: n.role, content: n.content }))
    
    const input: UserInput = {
      content: parentNode.content, // The user message to retry from
      agent_id: agentId,
      thread_id: treeManager.getThreadId(),
      thinking_mode: thinkingMode,
    }
    
    let streamedContent = ""
    
    try {
      await streamChat(
        input,
        (event: StreamEvent) => {
          if (event.type === "token") {
            streamedContent += event.content
            treeManager.updateNodeContent(assistantNode.id, streamedContent)
            updateCurrentPath()
          } else if (event.type === "message") {
            treeManager.updateNodeContent(assistantNode.id, event.content.content)
            updateCurrentPath()
          }
        },
        controller.signal,
      )
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        console.error("Streaming error:", error)
      }
    } finally {
      setIsStreaming(false)
      setAbortController(null)
      
      const finalNode = treeManager.getNode(assistantNode.id)
      if (finalNode) {
        await updateMessageNode(assistantNode.id, { content: finalNode.content })
      }
    }
  }, [treeManager, agentId, thinkingMode, isLocked, isStreaming, updateCurrentPath])

  // Quote a message
  const quote = useCallback(async (nodeId: string, newContent: string) => {
    if (isLocked || isStreaming) return
    
    const node = treeManager.getNode(nodeId)
    if (!node) return
    
    // Format quoted content
    const quotedContent = `> ${node.content}\n\n${newContent}`
    
    // Create new user message at the end of current path
    const currentLeaf = treeManager.getCurrentLeaf()
    const userNodeData: MessageNodeCreate = {
      thread_id: treeManager.getThreadId()!,
      role: "user",
      content: quotedContent,
      parent_id: currentLeaf?.id || null,
    }
    const userNode = await createMessageNode(userNodeData)
    treeManager.addNode(userNode)
    treeManager.setCurrentLeafId(userNode.id)
    updateCurrentPath()
    
    // Create assistant node
    const assistantNodeData = treeManager.createNewAssistantMessage(userNode.id)
    const assistantNode = await createMessageNode(assistantNodeData)
    treeManager.addNode(assistantNode)
    treeManager.setCurrentLeafId(assistantNode.id)
    updateCurrentPath()
    
    await updateCurrentLeaf(treeManager.getThreadId()!, assistantNode.id)
    
    // Start streaming
    setIsStreaming(true)
    const controller = new AbortController()
    setAbortController(controller)
    
    const input: UserInput = {
      content: quotedContent,
      agent_id: agentId,
      thread_id: treeManager.getThreadId(),
      thinking_mode: thinkingMode,
    }
    
    let streamedContent = ""
    
    try {
      await streamChat(
        input,
        (event: StreamEvent) => {
          if (event.type === "token") {
            streamedContent += event.content
            treeManager.updateNodeContent(assistantNode.id, streamedContent)
            updateCurrentPath()
          } else if (event.type === "message") {
            treeManager.updateNodeContent(assistantNode.id, event.content.content)
            updateCurrentPath()
          }
        },
        controller.signal,
      )
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        console.error("Streaming error:", error)
      }
    } finally {
      setIsStreaming(false)
      setAbortController(null)
      
      const finalNode = treeManager.getNode(assistantNode.id)
      if (finalNode) {
        await updateMessageNode(assistantNode.id, { content: finalNode.content })
      }
    }
  }, [treeManager, agentId, thinkingMode, isLocked, isStreaming, updateCurrentPath])

  // Edit user message
  const editUserMessage = useCallback(async (nodeId: string, newContent: string) => {
    if (isLocked || isStreaming) return
    
    const node = treeManager.getNode(nodeId)
    if (!node || node.role !== "user") return
    
    // Create a new user node as sibling (branch)
    const newBranchIndex = treeManager.getNextBranchIndex(node.parent_id)
    const userNodeData: MessageNodeCreate = {
      thread_id: treeManager.getThreadId()!,
      role: "user",
      content: newContent,
      parent_id: node.parent_id,
      branch_index: newBranchIndex,
    }
    const userNode = await createMessageNode(userNodeData)
    treeManager.addNode(userNode)
    treeManager.setCurrentLeafId(userNode.id)
    updateCurrentPath()
    
    // Create assistant node
    const assistantNodeData = treeManager.createNewAssistantMessage(userNode.id)
    const assistantNode = await createMessageNode(assistantNodeData)
    treeManager.addNode(assistantNode)
    treeManager.setCurrentLeafId(assistantNode.id)
    updateCurrentPath()
    
    await updateCurrentLeaf(treeManager.getThreadId()!, assistantNode.id)
    
    // Start streaming
    setIsStreaming(true)
    const controller = new AbortController()
    setAbortController(controller)
    
    const input: UserInput = {
      content: newContent,
      agent_id: agentId,
      thread_id: treeManager.getThreadId(),
      thinking_mode: thinkingMode,
    }
    
    let streamedContent = ""
    
    try {
      await streamChat(
        input,
        (event: StreamEvent) => {
          if (event.type === "token") {
            streamedContent += event.content
            treeManager.updateNodeContent(assistantNode.id, streamedContent)
            updateCurrentPath()
          } else if (event.type === "message") {
            treeManager.updateNodeContent(assistantNode.id, event.content.content)
            updateCurrentPath()
          }
        },
        controller.signal,
      )
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        console.error("Streaming error:", error)
      }
    } finally {
      setIsStreaming(false)
      setAbortController(null)
      
      const finalNode = treeManager.getNode(assistantNode.id)
      if (finalNode) {
        await updateMessageNode(assistantNode.id, { content: finalNode.content })
      }
    }
  }, [treeManager, agentId, thinkingMode, isLocked, isStreaming, updateCurrentPath])

  // Switch branch
  const switchBranch = useCallback(async (nodeId: string) => {
    if (isLocked) return
    
    treeManager.switchToBranch(nodeId)
    updateCurrentPath()
    
    // Update current_leaf_id on server
    const currentLeafId = treeManager.getCurrentLeafId()
    if (currentLeafId && treeManager.getThreadId()) {
      await updateCurrentLeaf(treeManager.getThreadId()!, currentLeafId)
    }
  }, [treeManager, isLocked, updateCurrentPath])

  const value: ConversationContextType = {
    threadId,
    agentId,
    thinkingMode,
    isLoading,
    isStreaming,
    isLocked,
    lockedLeafId,
    currentPath,
    loadTree,
    clearTree,
    sendMessage,
    retry,
    quote,
    editUserMessage,
    switchBranch,
    setAgentId,
    setThinkingMode,
    getTreeManager: () => treeManager,
  }

  return (
    <ConversationContext.Provider value={value}>
      {children}
    </ConversationContext.Provider>
  )
}

// Hook
export function useConversation(): ConversationContextType {
  const context = useContext(ConversationContext)
  if (!context) {
    throw new Error("useConversation must be used within a ConversationProvider")
  }
  return context
}