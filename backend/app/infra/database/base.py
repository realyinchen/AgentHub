"""
Database base module.

Exposes the SQLAlchemy declarative `Base` used by all ORM models.
This module deliberately has no dependency on concrete backends so that
ORM model files can import it without triggering backend initialization.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for ORM models."""

    pass


__all__ = ["Base"]
