"""seed catalog

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

models = sa.table("models", sa.column("slug", sa.String), sa.column("price", sa.Integer))
legs = sa.table(
    "legs",
    sa.column("model_slug", sa.String),
    sa.column("provider", sa.String),
    sa.column("priority", sa.Integer),
    sa.column("max_ref_images", sa.Integer),
    sa.column("skip_on_moderation", sa.Boolean),
)


def upgrade() -> None:
    op.bulk_insert(
        models,
        [
            {"slug": "image-fast", "price": 2},
            {"slug": "video-long", "price": 25},
        ],
    )
    op.bulk_insert(
        legs,
        [
            {
                "model_slug": "image-fast",
                "provider": "alpha",
                "priority": 1,
                "max_ref_images": 4,
                "skip_on_moderation": False,
            },
            {
                "model_slug": "image-fast",
                "provider": "beta",
                "priority": 2,
                "max_ref_images": 10,
                "skip_on_moderation": False,
            },
            {
                "model_slug": "video-long",
                "provider": "beta",
                "priority": 1,
                "max_ref_images": 2,
                "skip_on_moderation": False,
            },
            {
                "model_slug": "video-long",
                "provider": "alpha",
                "priority": 2,
                "max_ref_images": 1,
                "skip_on_moderation": True,
            },
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM legs WHERE model_slug IN ('image-fast', 'video-long')")
    op.execute("DELETE FROM models WHERE slug IN ('image-fast', 'video-long')")
