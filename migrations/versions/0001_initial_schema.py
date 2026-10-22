"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "models",
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.CheckConstraint("price > 0", name=op.f("ck_models_price_positive")),
        sa.PrimaryKeyConstraint("slug", name=op.f("pk_models")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("balance", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("balance >= 0", name=op.f("ck_users_balance_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "legs",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("model_slug", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("max_ref_images", sa.Integer(), nullable=False),
        sa.Column("skip_on_moderation", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("max_ref_images >= 0", name=op.f("ck_legs_max_ref_images_non_negative")),
        sa.ForeignKeyConstraint(["model_slug"], ["models.slug"], name=op.f("fk_legs_model_slug_models")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legs")),
        sa.UniqueConstraint("model_slug", "priority", name=op.f("uq_legs_model_slug_priority")),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("model_slug", sa.String(length=64), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("ref_images", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result_url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('processing', 'completed', 'failed')", name=op.f("ck_tasks_status_valid")),
        sa.ForeignKeyConstraint(["model_slug"], ["models.slug"], name=op.f("fk_tasks_model_slug_models")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_tasks_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(
        "ix_tasks_user_id_processing",
        "tasks",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.create_table(
        "attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("leg_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("error_type", sa.String(length=16), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("result_url", sa.Text(), nullable=True),
        sa.Column("late_result", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "error_type IS NULL OR error_type IN ('technical', 'moderation', 'payload', 'timeout')",
            name=op.f("ck_attempts_error_type_valid"),
        ),
        sa.CheckConstraint(
            "late_result IS NULL OR late_result IN ('accepted', 'ignored')", name=op.f("ck_attempts_late_result_valid")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'completed', 'failed', 'timed_out', 'cancelled')",
            name=op.f("ck_attempts_status_valid"),
        ),
        sa.ForeignKeyConstraint(["leg_id"], ["legs.id"], name=op.f("fk_attempts_leg_id_legs")),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_attempts_task_id_tasks")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attempts")),
    )
    op.create_index(
        "ix_attempts_deadline_at_active",
        "attempts",
        ["deadline_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'sent')"),
    )
    op.create_index("ix_attempts_task_id", "attempts", ["task_id"], unique=False)
    op.create_index(
        "uq_attempts_task_id_active",
        "attempts",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'sent')"),
    )
    op.create_table(
        "ledger",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("payment_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(reason <> 'topup') = (task_id IS NOT NULL)", name=op.f("ck_ledger_task_entry_has_task")),
        sa.CheckConstraint("(reason = 'topup') = (payment_id IS NOT NULL)", name=op.f("ck_ledger_topup_has_payment")),
        sa.CheckConstraint("reason IN ('topup', 'charge', 'refund')", name=op.f("ck_ledger_reason_valid")),
        sa.CheckConstraint("amount <> 0", name=op.f("ck_ledger_amount_non_zero")),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_ledger_task_id_tasks")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ledger_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger")),
    )
    op.create_index("ix_ledger_user_id_id", "ledger", ["user_id", "id"], unique=False)
    op.create_index(
        "uq_ledger_payment_id",
        "ledger",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("payment_id IS NOT NULL"),
    )
    op.create_index(
        "uq_ledger_task_id_reason",
        "ledger",
        ["task_id", "reason"],
        unique=True,
        postgresql_where=sa.text("task_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("ledger")
    op.drop_table("attempts")
    op.drop_table("tasks")
    op.drop_table("legs")
    op.drop_table("users")
    op.drop_table("models")
