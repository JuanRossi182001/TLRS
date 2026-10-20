"""require assets for active devices

Revision ID: d4f8a2c6e9b1
Revises: e1c4a8b9d2f3
Create Date: 2026-07-22 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d4f8a2c6e9b1"
down_revision: Union[str, Sequence[str], None] = "e1c4a8b9d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Preserve historical records while making invalid active devices safe.
    op.execute(
        """
        UPDATE devices
        SET active = false, state = 'OFF'
        WHERE active = true AND asset_id IS NULL
        """
    )
    op.create_check_constraint(
        "ck_devices_active_requires_asset",
        "devices",
        "active = false OR asset_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_devices_active_requires_asset",
        "devices",
        type_="check",
    )
