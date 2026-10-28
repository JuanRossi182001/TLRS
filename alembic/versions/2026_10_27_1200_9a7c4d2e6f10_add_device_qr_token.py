"""add stable QR identity to devices

Revision ID: 9a7c4d2e6f10
Revises: f8b2a6d4c1e9
Create Date: 2026-10-27 12:00:00.000000
"""

import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9a7c4d2e6f10"
down_revision: Union[str, Sequence[str], None] = "f8b2a6d4c1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BACKFILL_BATCH_SIZE = 500


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("qr_token", sa.String(length=43), nullable=True),
    )

    bind = op.get_bind()
    while True:
        rows = bind.execute(
            sa.text(
                """
                SELECT id_device
                FROM devices
                WHERE qr_token IS NULL
                ORDER BY id_device
                LIMIT :batch_size
                """
            ),
            {"batch_size": BACKFILL_BATCH_SIZE},
        ).all()
        if not rows:
            break

        updates = [
            {"device_id": row.id_device, "qr_token": secrets.token_urlsafe(32)}
            for row in rows
        ]
        bind.execute(
            sa.text(
                "UPDATE devices SET qr_token = :qr_token "
                "WHERE id_device = :device_id AND qr_token IS NULL"
            ),
            updates,
        )
    op.create_index(
        "uq_devices_qr_token",
        "devices",
        ["qr_token"],
        unique=True,
    )
    op.alter_column(
        "devices",
        "qr_token",
        existing_type=sa.String(length=43),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_index("uq_devices_qr_token", table_name="devices")
    op.drop_column("devices", "qr_token")
