import type { MessageNode, MessageTree, MessageNodeCreate } from "@/types/message-tree";

/**
 * MessageTreeManager - Core class for managing tree-structured conversation history.
 * This implements Grok-style branching chat with retry, quote, and edit operations.
 */
export class MessageTreeManager {
  private nodes: Map<string, MessageNode> = new Map();
  private rootId: string | null = null;
  private currentLeafId: string | null = null;
  private threadId: string | null = null;

  /**
   * Load a message tree from the server response.
   */
  loadFromTree(tree: MessageTree): void {
    this.nodes.clear();
    this.threadId = tree.nodes.length > 0 ? tree.nodes[0].thread_id : null;
    
    for (const node of tree.nodes) {
      this.nodes.set(node.id, node);
    }
    
    this.rootId = tree.root_id;
    this.currentLeafId = tree.current_leaf_id;
  }

  /**
   * Get the current path from root to current leaf.
   * This is what gets displayed in the chat UI.
   */
  getCurrentPath(): MessageNode[] {
    if (!this.currentLeafId) {
      return [];
    }
    return this.getPathToNode(this.currentLeafId);
  }

  /**
   * Get the path from root to a specific node.
   * Returns nodes in order from root to the target node.
   */
  getPathToNode(nodeId: string): MessageNode[] {
    const path: MessageNode[] = [];
    let currentId: string | null = nodeId;

    while (currentId) {
      const node = this.nodes.get(currentId);
      if (!node) {
        break;
      }
      path.unshift(node);
      currentId = node.parent_id;
    }

    return path;
  }

  /**
   * Get a node by ID.
   */
  getNode(nodeId: string): MessageNode | undefined {
    return this.nodes.get(nodeId);
  }

  /**
   * Get children of a node.
   */
  getChildren(nodeId: string | null): MessageNode[] {
    const children: MessageNode[] = [];
    for (const node of this.nodes.values()) {
      if (node.parent_id === nodeId) {
        children.push(node);
      }
    }
    return children.sort((a, b) => a.branch_index - b.branch_index);
  }

  /**
   * Get the current leaf node.
   */
  getCurrentLeaf(): MessageNode | undefined {
    if (!this.currentLeafId) {
      return undefined;
    }
    return this.nodes.get(this.currentLeafId);
  }

  /**
   * Get the root node.
   */
  getRoot(): MessageNode | undefined {
    if (!this.rootId) {
      return undefined;
    }
    return this.nodes.get(this.rootId);
  }

  /**
   * Add a new node to the tree.
   */
  addNode(node: MessageNode): void {
    this.nodes.set(node.id, node);
    
    // Update parent's children_ids if parent exists
    if (node.parent_id) {
      const parent = this.nodes.get(node.parent_id);
      if (parent && !parent.children_ids.includes(node.id)) {
        parent.children_ids.push(node.id);
      }
    }
    
    // If this is the first node, set it as root
    if (!this.rootId && node.parent_id === null) {
      this.rootId = node.id;
    }
  }

  /**
   * Update the current leaf ID.
   */
  setCurrentLeafId(leafId: string): void {
    this.currentLeafId = leafId;
  }

  /**
   * Update a node's content.
   */
  updateNodeContent(nodeId: string, content: string): void {
    const node = this.nodes.get(nodeId);
    if (node) {
      node.content = content;
    }
  }

  /**
   * Get the thread ID.
   */
  getThreadId(): string | null {
    return this.threadId;
  }

  /**
   * Set the thread ID.
   */
  setThreadId(threadId: string): void {
    this.threadId = threadId;
  }

  /**
   * Get the current leaf ID.
   */
  getCurrentLeafId(): string | null {
    return this.currentLeafId;
  }

  /**
   * Get the root ID.
   */
  getRootId(): string | null {
    return this.rootId;
  }

  /**
   * Check if the tree is empty.
   */
  isEmpty(): boolean {
    return this.nodes.size === 0;
  }

  /**
   * Get all nodes.
   */
  getAllNodes(): MessageNode[] {
    return Array.from(this.nodes.values());
  }

  /**
   * Clear the tree.
   */
  clear(): void {
    this.nodes.clear();
    this.rootId = null;
    this.currentLeafId = null;
    this.threadId = null;
  }

  /**
   * Get messages for API request.
   * Returns the current path as an array of { role, content } objects.
   */
  getMessagesForAPI(): Array<{ role: "user" | "assistant"; content: string }> {
    const path = this.getCurrentPath();
    return path.map((node) => ({
      role: node.role,
      content: node.content,
    }));
  }

  /**
   * Create a new user message node (for sending).
   */
  createNewUserMessage(content: string): MessageNodeCreate {
    const currentLeaf = this.getCurrentLeaf();
    return {
      thread_id: this.threadId || "",
      role: "user",
      content,
      parent_id: currentLeaf?.id || null,
    };
  }

  /**
   * Create a new assistant message node (for streaming).
   */
  createNewAssistantMessage(parentId: string): MessageNodeCreate {
    return {
      thread_id: this.threadId || "",
      role: "assistant",
      content: "",
      parent_id: parentId,
    };
  }

  /**
   * Check if a node has siblings (other branches).
   */
  hasSiblings(nodeId: string): boolean {
    const node = this.nodes.get(nodeId);
    if (!node || !node.parent_id) {
      return false;
    }
    const siblings = this.getChildren(node.parent_id);
    return siblings.length > 1;
  }

  /**
   * Get sibling nodes (other branches at the same level).
   */
  getSiblings(nodeId: string): MessageNode[] {
    const node = this.nodes.get(nodeId);
    if (!node) {
      return [];
    }
    const siblings = this.getChildren(node.parent_id || null);
    return siblings.filter((s) => s.id !== nodeId);
  }

  /**
   * Get the branch index for a new sibling.
   */
  getNextBranchIndex(parentId: string | null): number {
    const children = this.getChildren(parentId);
    if (children.length === 0) {
      return 0;
    }
    return Math.max(...children.map((c) => c.branch_index)) + 1;
  }

  /**
   * Switch to a different branch.
   * @param nodeId The node to switch to (must be a leaf or will find the latest leaf in that branch)
   */
  switchToBranch(nodeId: string): void {
    // Find the leaf node in this branch
    let leafId = nodeId;
    let node = this.nodes.get(nodeId);
    
    while (node && node.children_ids.length > 0) {
      // Follow the first child (or we could store preferred child)
      leafId = node.children_ids[0];
      node = this.nodes.get(leafId);
    }
    
    this.currentLeafId = leafId;
  }

  /**
   * Export the tree for serialization.
   */
  toMessageTree(): MessageTree {
    return {
      nodes: this.getAllNodes(),
      root_id: this.rootId,
      current_leaf_id: this.currentLeafId,
    };
  }
}

// Singleton instance for global access
let globalTreeManager: MessageTreeManager | null = null;

export function getMessageTreeManager(): MessageTreeManager {
  if (!globalTreeManager) {
    globalTreeManager = new MessageTreeManager();
  }
  return globalTreeManager;
}

export function resetMessageTreeManager(): void {
  globalTreeManager = null;
}