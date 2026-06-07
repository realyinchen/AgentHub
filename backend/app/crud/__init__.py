"""CRUD module for database operations."""

from app.crud.user import (
    get_user,
    get_user_by_channel_user_id,
    get_mock_users,
    create_user,
    update_user,
    delete_user,
)
from app.crud.user_channel import (
    get_user_channel,
    get_user_channel_by_user_and_channel,
    get_user_channel_by_channel_user_id,
    get_user_channels,
    create_user_channel,
    update_user_channel,
    update_channel_credentials,
    update_last_contact,
    delete_user_channel,
    get_or_create_user_channel,
)

__all__ = [
    # User CRUD
    "get_user",
    "get_user_by_channel_user_id",
    "get_mock_users",
    "create_user",
    "update_user",
    "delete_user",
    # UserChannel CRUD
    "get_user_channel",
    "get_user_channel_by_user_and_channel",
    "get_user_channel_by_channel_user_id",
    "get_user_channels",
    "create_user_channel",
    "update_user_channel",
    "update_channel_credentials",
    "update_last_contact",
    "delete_user_channel",
    "get_or_create_user_channel",
]
