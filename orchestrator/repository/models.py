from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ActionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    display: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="command")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ActionStatus.PENDING.value, index=True
    )
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"Action(id={self.id}, type={self.action_type!r}, status={self.status!r})"

# class Correction(Base):
#     __tablename__ = "corrections"

#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
#     original: Mapped[str] = mapped_column(Text, nullable=False)
#     corrected: Mapped[str] = mapped_column(Text, nullable=False)
#     user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
#     created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

#     def __repr__(self) -> str:
#         return f"Correction(id={self.id}, type={self.action_type!r})"