import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("balance >= 0", name="balance_non_negative"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    balance: Mapped[int] = mapped_column(BigInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GenerationModel(Base):
    __tablename__ = "models"
    __table_args__ = (CheckConstraint("price > 0", name="price_positive"),)

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    price: Mapped[int] = mapped_column(Integer)

    legs: Mapped[list["Leg"]] = relationship(order_by="Leg.priority", lazy="raise")


class Leg(Base):
    __tablename__ = "legs"
    __table_args__ = (
        UniqueConstraint("model_slug", "priority"),
        CheckConstraint("max_ref_images >= 0", name="max_ref_images_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    model_slug: Mapped[str] = mapped_column(ForeignKey("models.slug"))
    provider: Mapped[str] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer)
    max_ref_images: Mapped[int] = mapped_column(Integer)
    skip_on_moderation: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'completed', 'failed')", name="status_valid"),
        Index(
            "ix_tasks_user_id_processing",
            "user_id",
            postgresql_where=text("status = 'processing'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    model_slug: Mapped[str] = mapped_column(ForeignKey("models.slug"))
    prompt: Mapped[str] = mapped_column(Text)
    ref_images: Mapped[list[str]] = mapped_column(JSONB)
    price: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    result_url: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'completed', 'failed', 'timed_out', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint(
            "error_type IS NULL OR error_type IN ('technical', 'moderation', 'payload', 'timeout')",
            name="error_type_valid",
        ),
        CheckConstraint(
            "late_result IS NULL OR late_result IN ('accepted', 'ignored')",
            name="late_result_valid",
        ),
        Index(
            "uq_attempts_task_id_active",
            "task_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'sent')"),
        ),
        Index(
            "ix_attempts_deadline_at_active",
            "deadline_at",
            postgresql_where=text("status IN ('pending', 'sent')"),
        ),
        Index("ix_attempts_task_id", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"))
    leg_id: Mapped[int] = mapped_column(ForeignKey("legs.id"))
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str | None] = mapped_column(String(128))
    error_type: Mapped[str | None] = mapped_column(String(16))
    error_detail: Mapped[str | None] = mapped_column(Text)
    result_url: Mapped[str | None] = mapped_column(Text)
    late_result: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    leg: Mapped[Leg] = relationship(lazy="raise")


class LedgerEntry(Base):
    __tablename__ = "ledger"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="amount_non_zero"),
        CheckConstraint("reason IN ('topup', 'charge', 'refund')", name="reason_valid"),
        CheckConstraint("(reason = 'topup') = (payment_id IS NOT NULL)", name="topup_has_payment"),
        CheckConstraint("(reason <> 'topup') = (task_id IS NOT NULL)", name="task_entry_has_task"),
        Index(
            "uq_ledger_payment_id",
            "payment_id",
            unique=True,
            postgresql_where=text("payment_id IS NOT NULL"),
        ),
        Index(
            "uq_ledger_task_id_reason",
            "task_id",
            "reason",
            unique=True,
            postgresql_where=text("task_id IS NOT NULL"),
        ),
        Index("ix_ledger_user_id_id", "user_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(16))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"))
    payment_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
