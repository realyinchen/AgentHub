/**
 * Hook for managing conversation tree state.
 * This is a simpler wrapper around the MessageTreeManager for use in components.
 */
import { useCallback, useState } from "react"
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

export interface UseConversationTreeOptions {
  threadId: string | null
  agentId: string
  thinkingMode?: boolean
}

export interface UseConversationTreeReturn {
  // State
  currentPath: MessageNode[]
  isLoading: boolean
  isStreaming: boolean
  isLocked: boolean
  
  // Actions
  loadTree: (threadId: string, leafId?: string) => Promise<void>
  clearTree: () => void
  sendMessage: (content: string) => Promise<void>
  retry: (nodeId: string) => Promise<void>
  quote: (nodeId: string, newContent: string) => Promise<void>
  editUserMessage: (nodeId: string, newContent: string) => Promise<void>
  switchBranch: (nodeId: string) => Promise<void>
  
  // Tree access
  getTreeManager: () => MessageTreeManager
  getChildren: (parentId: string | null) => MessageNode[]
  hasSiblings: (nodeId: string) => boolean
  getSiblings: (nodeId: string) => MessageNode[]
}

export function useConversationTree({
  threadId,
  agentId,
  thinkingMode = false,
}: UseConversationTreeOptions): UseConversationTreeReturn {
  const [currentPath, setCurrentPath] = useState<MessageNode[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isLocked, setIsLocked] = useState(false)
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
      
      if (leafId) {
        setIsLocked(true)
      } else {
        setIsLocked(false)
      }
      
      updateCurrentPath()
    } catch (error) {
      console.error("Failed to load message tree:", error)
      // If tree doesn't exist yet, start with empty tree
      treeManager.clear()
      treeManager.setThreadId(newThreadId)
      setCurrentPath([])
    } finally {
      setIsLoading(false)
    }
  }, [treeManager, updateCurrentPath])

  // Clear tree
  const clearTree = useCallback(() => {
    resetMessageTreeManager()
    setCurrentPath([])
    setIsLocked(false)
  }, [])

  // Send message
  const sendMessage = useCallback(async (content: string) => {
    if (isLocked || isStreaming) return
    
    const currentThreadId = treeManager.getThreadId() || threadId
    if (!currentThreadId) return
    
    // Create user message node
    const userNodeData: MessageNodeCreate = {
      thread_id: currentThreadId,
      role: "user",
      content,
      parent_id: treeManager.getCurrentLeaf()?.id || null,
    }
    
    try {
      const userNode = await createMessageNode(userNodeData)
      treeManager.addNode(userNode)
      treeManager.setThreadId(currentThreadId)
      treeManager.setCurrentLeafId(userNode.id)
      updateCurrentPath()
      
      // Create assistant message node (empty, will be filled by streaming)
      const assistantNodeData: MessageNodeCreate = {
        thread_id: currentThreadId,
        role: "assistant",
        content: "",
        parent_id: userNode.id,
      }
      const assistantNode = await createMessageNode(assistantNodeData)
      treeManager.addNode(assistantNode)
      treeManager.setCurrentLeafId(assistantNode.id)
      updateCurrentPath()
      
      // Update current_leaf_id on server
      await updateCurrentLeaf(currentThreadId, assistantNode.id)
      
      // Start streaming
      setIsStreaming(true)
      const controller = new AbortController()
      setAbortController(controller)
      
      const input: UserInput = {
        content,
        agent_id: agentId,
        thread_id: currentThreadId,
        thinking_mode: thinkingMode,
      }
      
      let streamedContent = ""
      
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
      
      // Update the node on server with final content
      const finalNode = treeManager.getNode(assistantNode.id)
      if (finalNode) {
        await updateMessageNode(assistantNode.id, { content: finalNode.content })
      }
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        console.error("Streaming error:", error)
        throw error
      }
    } finally {
      setIsStreaming(false)
      setAbortController(null)
    }
  }, [threadId, agentId, thinkingMode, isLocked, isStreaming, treeManager, updateCurrentPath])

  // Retry (regenerate assistant message)
  const retry = useCallback(async (nodeId: string) => {
    if (isLocked || isStreaming) return
    
    const node = treeManager.getNode(nodeId)
    if (!node || node.role !== "assistant") return
    
    const parentNode = node.parent_id ? treeManager.getNode(node.parent_id) : null
    if (!parentNode || parentNode.role !== "user") return
    
    const currentThreadId = treeManager.getThreadId()
    if (!currentThreadId) return
    
    // Create a new assistant node as sibling
    const children = treeManager.getChildren(node.parent_id)
    const newBranchIndex = children.length > 0 
      ? Math.max(...children.map(c => c.branch_index)) + 1 
      : 0
    
    const assistantNodeData: MessageNodeCreate = {
      thread_id: currentThreadId,
      role: "assistant",
      content: "",
      parent_id: node.parent_id,
      branch_index: newBranchIndex,
    }
    
    try {
      const assistantNode = await createMessageNode(assistantNodeData)
      treeManager.addNode(assistantNode)
      treeManager.setCurrentLeafId(assistantNode.id)
      updateCurrentPath()
      
      await updateCurrentLeaf(currentThreadId, assistantNode.id)
      
      setIsStreaming(true)
      const controller = new AbortController()
      setAbortController(controller)
      
      const input: UserInput = {
        content: parentNode.content,
        agent_id: agentId,
        thread_id: currentThreadId,
        thinking_mode: thinkingMode,
      }
      
      let streamedContent = ""
      
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
      
      const finalNode = treeManager.getNode(assistantNode.id)
      if (finalNode) {
        await updateMessageNode(assistantNode.id, { content: finalNode.content })
      }
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        console.error("Streaming error:", error)
        throw error
      }
    } finally {
      setIsStreaming(false)
      setAbortController(null)
    }
  }, [agentId, thinkingMode, isLocked, isStreaming, treeManager, updateCurrentPath])

  // Quote a message
  const quote = useCallback(async (nodeId: string, newContent: string) => {
    if (isLocked || isStreaming) return
    
    const node = treeManager.getNode(nodeId)
    if (!node) return
    
    const currentThreadId = treeManager.getThreadId()
    if (!currentThreadId) return
    
    // Format quoted content
    const quotedContent = `> ${node.content}\n\n${newContent}`
    
    const currentLeaf = treeManager.getCurrentLeaf()
    const userNodeData: MessageNodeCreate = {
      thread_id: currentThreadId,
      role: "user",
      content: quotedContent,
      parent_id: currentLeaf?.id || null,
    }
    
    try {
      const userNode = await createMessageNode(userNodeData)
      treeManager.addNode(userNode)
      treeManager.setCurrentLeafId(userNode.id)
      updateCurrentPath()
      
      const assistantNodeData: MessageNodeCreate = {
        thread_id: currentThreadId,
        role: "assistant",
        content: "",
        parent_id: userNode.id,
      }
      const assistantNode = await createMessageNode(assistantNodeData)
      treeManager.addNode(assistantNode)
      treeManager.setCurrentLeafId(assistantNode.id)
      updateCurrentPath()
      
      await updateCurrentLeaf(currentThreadId, assistantNode.id)
      
      setIsStreaming(true)
      const controller = new AbortController()
      setAbortController(controller)
      
      const input: UserInput = {
        content: quotedContent,
        agent_id: agentId,
        thread_id: currentThreadId,
        thinking_mode: thinkingMode,
      }
      
      let streamedContent = ""
      
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
      
      const finalNode = treeManager.getNode(assistantNode.id)
      if (finalNode) {
        await updateMessageNode(assistantNode.id, { content: finalNode.content })
      }
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        console.error("Streaming error:", error)
        throw error
      }
    } finally {
      setIsStreaming(false)
      setAbortController(null)
    }
  }, [agentId, thinkingMode, isLocked, isStreaming, treeManager, updateCurrentPath])

  // Edit user message
  const editUserMessage = useCallback(async (nodeId: string, newContent: string) => {
    if (isLocked || isStreaming) return
    
    const node = treeManager.getNode(nodeId)
    if (!node || node.role !== "user") return
    
    const currentThreadId = treeManager.getThreadId()
    if (!currentThreadId) return
    
    // Create a new user node as sibling (branch)
    const siblings = treeManager.getChildren(node.parent_id || null)
    const newBranchIndex = siblings.length > 0 
      ? Math.max(...siblings.map(s => s.branch_index)) + 1 
      : 0
    
    const userNodeData: MessageNodeCreate = {
      thread_id: currentThreadId,
      role: "user",
      content: newContent,
      parent_id: node.parent_id,
      branch_index: newBranchIndex,
    }
    
    try {
      const userNode = await createMessageNode(userNodeData)
      treeManager.addNode(userNode)
      treeManager.setCurrentLeafId(userNode.id)
      updateCurrentPath()
      
      const assistantNodeData: MessageNodeCreate = {
        thread_id: currentThreadId,
        role: "assistant",
        content: "",
        parent_id: userNode.id,
      }
      const assistantNode = await createMessageNode(assistantNodeData)
      treeManager.addNode(assistantNode)
      treeManager.setCurrentLeafId(assistantNode.id)
      updateCurrentPath()
      
      await updateCurrentLeaf(currentThreadId, assistantNode.id)
      
      setIsStreaming(true)
      const controller = new AbortController()
      setAbortController(controller)
      
      const input: UserInput = {
        content: newContent,
        agent_id: agentId,
        thread_id: currentThreadId,
        thinking_mode: thinkingMode,
      }
      
      let streamedContent = ""
      
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
      
      const finalNode = treeManager.getNode(assistantNode.id)
      if (finalNode) {
        await updateMessageNode(assistantNode.id, { content: finalNode.content })
      }
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        console.error("Streaming error:", error)
        throw error
      }
    } finally {
      setIsStreaming(false)
      setAbortController(null)
    }
  }, [agentId, thinkingMode, isLocked, isStreaming, treeManager, updateCurrentPath])

  // Switch branch
  const switchBranch = useCallback(async (nodeId: string) => {
    if (isLocked) return
    
    treeManager.switchToBranch(nodeId)
    updateCurrentPath()
    
    const currentLeafId = treeManager.getCurrentLeafId()
    const currentThreadId = treeManager.getThreadId()
    if (currentLeafId && currentThreadId) {
      await updateCurrentLeaf(currentThreadId, currentLeafId)
    }
  }, [treeManager, isLocked, updateCurrentPath])

  // Get children of a node
  const getChildren = useCallback((parentId: string | null) => {
    return treeManager.getChildren(parentId)
  }, [treeManager])

  // Check if a node has siblings
  const hasSiblings = useCallback((nodeId: string) => {
    return treeManager.hasSiblings(nodeId)
  }, [treeManager])

  // Get siblings of a node
  const getSiblings = useCallback((nodeId: string) => {
    return treeManager.getSiblings(nodeId)
  }, [treeManager])

  return {
    currentPath,
    isLoading,
    isStreaming,
    isLocked,
    loadTree,
    clearTree,
    sendMessage,
    retry,
    quote,
    editUserMessage,
    switchBranch,
    getTreeManager: () => treeManager,
    getChildren,
    hasSiblings,
    getSiblings,
  }
}