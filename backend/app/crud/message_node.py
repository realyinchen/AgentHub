import logging
from uuid import UUID
from typing import List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message_node import MessageNode
from app.models.chat import Conversation
from app.schemas.message_node import (
    MessageNodeCreate,
    MessageNodeUpdate,
    MessageNodeInDB,
    MessageTree,
)

logger = logging.getLogger(__name__)


def _node_to_dict(node: MessageNode, children_ids: List[UUID] | None = None) -> dict:
    """Convert a MessageNode model to a dictionary for MessageNodeInDB."""
    return {
        "id": node.id,
        "thread_id": node.thread_id,
        "role": node.role,
        "content": node.content,
        "parent_id": node.parent_id,
        "branch_index": node.branch_index,
        "created_at": node.created_at,
        "tool_calls": node.tool_calls,
        "tool_call_status": node.tool_call_status,
        "custom_data": node.custom_data,
        "children_ids": children_ids or [],
    }


async def create_message_node(
    db: AsyncSession,
    node_in: MessageNodeCreate,
) -> MessageNodeInDB:
    """Create a new message node."""
    # Calculate branch_index if not provided
    if node_in.branch_index == 0 and node_in.parent_id:
        siblings = await get_children_by_parent_id(db, node_in.parent_id)
        node_in.branch_index = len(siblings)

    db_obj = MessageNode(
        thread_id=node_in.thread_id,
        role=node_in.role,
        content=node_in.content,
        parent_id=node_in.parent_id,
        branch_index=node_in.branch_index,
        tool_calls=node_in.tool_calls,
        tool_call_status=node_in.tool_call_status,
        custom_data=node_in.custom_data,
    )

    db.add(db_obj)
    await db.flush()
    await db.refresh(db_obj)

    return MessageNodeInDB.model_validate(_node_to_dict(db_obj))


async def get_message_node_by_id(
    db: AsyncSession,
    node_id: UUID,
) -> MessageNodeInDB | None:
    """Get a message node by ID."""
    stmt = select(MessageNode).where(MessageNode.id == node_id)
    result = await db.execute(stmt)
    node = result.scalar_one_or_none()

    if not node:
        return None

    # Get children IDs
    children_stmt = select(MessageNode.id).where(MessageNode.parent_id == node_id)
    children_result = await db.execute(children_stmt)
    children_ids = [row[0] for row in children_result.fetchall()]

    return MessageNodeInDB.model_validate(_node_to_dict(node, children_ids))


async def get_children_by_parent_id(
    db: AsyncSession,
    parent_id: UUID | None,
) -> List[MessageNodeInDB]:
    """Get all children of a parent node."""
    stmt = (
        select(MessageNode)
        .where(MessageNode.parent_id == parent_id)
        .order_by(MessageNode.branch_index, MessageNode.created_at)
    )
    result = await db.execute(stmt)
    nodes = result.scalars().all()

    return [MessageNodeInDB.model_validate(_node_to_dict(node)) for node in nodes]


async def get_message_tree(
    db: AsyncSession,
    thread_id: UUID,
    leaf_id: UUID | None = None,
) -> MessageTree:
    """
    Get the complete message tree for a conversation.
    
    Args:
        db: Database session
        thread_id: Thread ID
        leaf_id: Optional leaf ID for share links (if provided, use this instead of stored current_leaf_id)
    
    Returns:
        MessageTree with all nodes, root_id, and current_leaf_id
    """
    # Get all nodes for this thread
    stmt = (
        select(MessageNode)
        .where(MessageNode.thread_id == thread_id)
        .order_by(MessageNode.created_at)
    )
    result = await db.execute(stmt)
    nodes = result.scalars().all()

    if not nodes:
        return MessageTree(nodes=[], root_id=None, current_leaf_id=None)

    # Build children_ids for each node
    children_map: dict[UUID | None, List[UUID]] = {}
    for node in nodes:
        parent = node.parent_id
        if parent not in children_map:
            children_map[parent] = []
        children_map[parent].append(node.id)

    # Convert to MessageNodeInDB
    node_dict: dict[UUID, MessageNodeInDB] = {}
    root_id: UUID | None = None
    
    for node in nodes:
        if node.parent_id is None:
            root_id = node.id
        
        node_dict[node.id] = MessageNodeInDB.model_validate(
            _node_to_dict(node, children_map.get(node.id, []))
        )

    # Determine current_leaf_id
    current_leaf_id: UUID | None = None
    
    if leaf_id:
        # Use provided leaf_id (from share link)
        current_leaf_id = leaf_id
    else:
        # Get from conversation
        conv_stmt = select(Conversation.current_leaf_id).where(
            Conversation.thread_id == thread_id
        )
        conv_result = await db.execute(conv_stmt)
        current_leaf_id = conv_result.scalar_one_or_none()

        # If no current_leaf_id, use the last node (by creation time)
        if current_leaf_id is None and nodes:
            current_leaf_id = nodes[-1].id

    return MessageTree(
        nodes=list(node_dict.values()),
        root_id=root_id,
        current_leaf_id=current_leaf_id,
    )


async def update_message_node(
    db: AsyncSession,
    node_id: UUID,
    node_update: MessageNodeUpdate,
) -> MessageNodeInDB | None:
    """Update a message node."""
    stmt = select(MessageNode).where(MessageNode.id == node_id)
    result = await db.execute(stmt)
    node = result.scalar_one_or_none()

    if not node:
        return None

    update_data = node_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(node, field, value)

    await db.flush()
    await db.refresh(node)

    # Get children IDs
    children_stmt = select(MessageNode.id).where(MessageNode.parent_id == node_id)
    children_result = await db.execute(children_stmt)
    children_ids = [row[0] for row in children_result.fetchall()]

    return MessageNodeInDB.model_validate(_node_to_dict(node, children_ids))


async def update_current_leaf_id(
    db: AsyncSession,
    thread_id: UUID,
    leaf_id: UUID,
) -> bool:
    """Update the current_leaf_id for a conversation."""
    stmt = select(Conversation).where(Conversation.thread_id == thread_id)
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()

    if not conv:
        return False

    conv.current_leaf_id = leaf_id
    await db.flush()

    return True


async def get_path_to_node(
    db: AsyncSession,
    node_id: UUID,
) -> List[MessageNodeInDB]:
    """
    Get the path from root to a specific node.
    Returns nodes in order from root to the target node.
    """
    path: List[MessageNodeInDB] = []
    current_id: UUID | None = node_id

    while current_id:
        node = await get_message_node_by_id(db, current_id)
        if not node:
            break
        path.insert(0, node)
        current_id = node.parent_id

    return path


async def get_next_branch_index(
    db: AsyncSession,
    parent_id: UUID | None,
) -> int:
    """Get the next branch_index for a new sibling."""
    stmt = (
        select(func.max(MessageNode.branch_index))
        .where(MessageNode.parent_id == parent_id)
    )
    result = await db.execute(stmt)
    max_index = result.scalar_one_or_none()

    return (max_index or 0) + 1 if max_index is not None else 0


async def delete_message_node_and_children(
    db: AsyncSession,
    node_id: UUID,
) -> bool:
    """Delete a message node and all its children (cascade delete)."""
    stmt = select(MessageNode).where(MessageNode.id == node_id)
    result = await db.execute(stmt)
    node = result.scalar_one_or_none()

    if not node:
        return False

    # Due to ON DELETE CASCADE in the model, children will be deleted automatically
    await db.delete(node)
    await db.flush()

    return True