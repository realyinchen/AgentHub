"""
Database Base Module

Re-exports abstract base classes and ORM base for convenience.
Business code should import from here rather than internal modules.
"""

from app.database.interfaces import (
    DatabaseInterface,
    VectorstoreInterface,
    CheckpointInterface,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for ORM models."""

    pass


__all__ = [
    "Base",
    "DatabaseInterface",
    "VectorstoreInterface",
    "CheckpointInterface",
]
