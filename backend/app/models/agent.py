from sqlalchemy import Column, Boolean, String, DateTime
from datetime import datetime, timezone

from app.database.base import Base


def utc_now():
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"

    agent_id = Column(String(64), primary_key=True)
    description = Column(String(1024), primary_key=True)
    is_active = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
