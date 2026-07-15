"""add chirpstack device provisioning

Revision ID: e1c4a8b9d2f3
Revises: 8c6e1b2f4a90
Create Date: 2026-07-15 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1c4a8b9d2f3"
down_revision: Union[str, Sequence[str], None] = "8c6e1b2f4a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("join_eui", sa.String(), nullable=True))
    op.add_column(
        "devices",
        sa.Column(
            "provisioning_status",
            sa.String(),
            nullable=False,
            server_default="NOT_PROVISIONED",
        ),
    )
    op.add_column("devices", sa.Column("provisioned_at", sa.DateTime(), nullable=True))
    op.add_column("devices", sa.Column("provisioning_error", sa.Text(), nullable=True))
    op.add_column("devices", sa.Column("app_key_last4", sa.String(length=4), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE devices
            SET provisioning_status = 'PROVISIONED'
            WHERE communication_protocol = 'CHIRPSTACK'
            """
        )
    )


def downgrade() -> None:
    op.drop_column("devices", "app_key_last4")
    op.drop_column("devices", "provisioning_error")
    op.drop_column("devices", "provisioned_at")
    op.drop_column("devices", "provisioning_status")
    op.drop_column("devices", "join_eui")
