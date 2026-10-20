"""add device asset assignment history

Revision ID: b7c3d5e9f1a2
Revises: d4f8a2c6e9b1
Create Date: 2026-08-18 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c3d5e9f1a2"
down_revision: Union[str, Sequence[str], None] = "d4f8a2c6e9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_asset_assignments",
        sa.Column("id_device_asset_assignment", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("unassigned_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.CheckConstraint(
            "unassigned_at IS NULL OR unassigned_at >= assigned_at",
            name="ck_device_asset_assignments_valid_interval",
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id_asset"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id_device"]),
        sa.PrimaryKeyConstraint("id_device_asset_assignment"),
    )
    op.create_index(
        "uq_device_asset_assignments_device_active",
        "device_asset_assignments",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text("unassigned_at IS NULL"),
    )
    op.create_index(
        "uq_device_asset_assignments_asset_active",
        "device_asset_assignments",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("unassigned_at IS NULL"),
    )
    op.create_index(
        "idx_device_asset_assignments_device_assigned_at",
        "device_asset_assignments",
        ["device_id", "assigned_at"],
    )
    op.create_index(
        "idx_device_asset_assignments_asset_assigned_at",
        "device_asset_assignments",
        ["asset_id", "assigned_at"],
    )

    # Existing rows do not contain an authoritative assignment timestamp. The
    # migration instant is the conservative start of trustworthy history.
    op.execute(
        sa.text(
            """
            INSERT INTO device_asset_assignments (
                device_id,
                asset_id,
                assigned_at,
                created_at
            )
            SELECT
                devices.id_device,
                devices.asset_id,
                timezone('utc', now()),
                timezone('utc', now())
            FROM devices
            WHERE devices.deleted = 'N'
              AND devices.asset_id IS NOT NULL
            ON CONFLICT (device_id) WHERE unassigned_at IS NULL DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "idx_device_asset_assignments_asset_assigned_at",
        table_name="device_asset_assignments",
    )
    op.drop_index(
        "idx_device_asset_assignments_device_assigned_at",
        table_name="device_asset_assignments",
    )
    op.drop_index(
        "uq_device_asset_assignments_asset_active",
        table_name="device_asset_assignments",
    )
    op.drop_index(
        "uq_device_asset_assignments_device_active",
        table_name="device_asset_assignments",
    )
    op.drop_table("device_asset_assignments")
