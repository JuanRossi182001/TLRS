"""add asset groups

Revision ID: 5b4b3db4ef01
Revises: 8c1f2a9b7d44
Create Date: 2026-06-16 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5b4b3db4ef01"
down_revision: Union[str, Sequence[str], None] = "8c1f2a9b7d44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_groups",
        sa.Column("id_asset_group", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("deleted", sa.String(length=1), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id_client"]),
        sa.PrimaryKeyConstraint("id_asset_group"),
    )
    op.create_index(
        "idx_asset_groups_client_id",
        "asset_groups",
        ["client_id"],
    )
    op.create_index(
        "uq_asset_groups_client_name_active",
        "asset_groups",
        ["client_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted = 'N'"),
    )

    op.create_table(
        "asset_group_members",
        sa.Column("id_asset_group_member", sa.Integer(), nullable=False),
        sa.Column("asset_group_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("deleted", sa.String(length=1), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_group_id"], ["asset_groups.id_asset_group"]),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id_asset"]),
        sa.PrimaryKeyConstraint("id_asset_group_member"),
    )
    op.create_index(
        "idx_asset_group_members_asset_group_id",
        "asset_group_members",
        ["asset_group_id"],
    )
    op.create_index(
        "idx_asset_group_members_asset_id",
        "asset_group_members",
        ["asset_id"],
    )
    op.create_index(
        "uq_asset_group_members_group_asset_active",
        "asset_group_members",
        ["asset_group_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("deleted = 'N'"),
    )

    op.create_table(
        "geofence_asset_groups",
        sa.Column("id_geofence_asset_group", sa.Integer(), nullable=False),
        sa.Column("geofence_id", sa.Integer(), nullable=False),
        sa.Column("asset_group_id", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("deleted", sa.String(length=1), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("unassigned_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_group_id"], ["asset_groups.id_asset_group"]),
        sa.ForeignKeyConstraint(["geofence_id"], ["geofences.id_geofence"]),
        sa.PrimaryKeyConstraint("id_geofence_asset_group"),
    )
    op.create_index(
        "idx_geofence_asset_groups_geofence_id",
        "geofence_asset_groups",
        ["geofence_id"],
    )
    op.create_index(
        "idx_geofence_asset_groups_asset_group_id",
        "geofence_asset_groups",
        ["asset_group_id"],
    )
    op.create_index(
        "uq_geofence_asset_groups_geofence_group_active",
        "geofence_asset_groups",
        ["geofence_id", "asset_group_id"],
        unique=True,
        postgresql_where=sa.text("deleted = 'N' AND active = true"),
    )

    op.create_index(
        "uq_devices_asset_id_active",
        "devices",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("deleted = 'N' AND asset_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_devices_asset_id_active", table_name="devices")

    op.drop_index(
        "uq_geofence_asset_groups_geofence_group_active",
        table_name="geofence_asset_groups",
    )
    op.drop_index(
        "idx_geofence_asset_groups_asset_group_id",
        table_name="geofence_asset_groups",
    )
    op.drop_index(
        "idx_geofence_asset_groups_geofence_id",
        table_name="geofence_asset_groups",
    )
    op.drop_table("geofence_asset_groups")

    op.drop_index(
        "uq_asset_group_members_group_asset_active",
        table_name="asset_group_members",
    )
    op.drop_index(
        "idx_asset_group_members_asset_id",
        table_name="asset_group_members",
    )
    op.drop_index(
        "idx_asset_group_members_asset_group_id",
        table_name="asset_group_members",
    )
    op.drop_table("asset_group_members")

    op.drop_index("uq_asset_groups_client_name_active", table_name="asset_groups")
    op.drop_index("idx_asset_groups_client_id", table_name="asset_groups")
    op.drop_table("asset_groups")
