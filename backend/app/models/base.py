"""Shared SQLAlchemy utilities for all ORM models."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC datetime with timezone information.

    Used as the default factory for ``created_at`` and ``updated_at``
    columns across all models.  Defined once here to avoid the
    identical five-copy duplication that existed before.
    """
    return datetime.now(timezone.utc)
