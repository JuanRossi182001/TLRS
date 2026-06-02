"""GeoFenceAssetState

Revision ID: 90492c6dd84e
Revises: 57d10e96a538
Create Date: 2026-06-02 09:28:29.410847

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '90492c6dd84e'
down_revision: Union[str, Sequence[str], None] = '57d10e96a538'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

geofence_status_enum = postgresql.ENUM(
    "SAFE",
    "NEAR_LIMIT",
    "OUTSIDE",
    "GPS_UNCERTAIN",
    name="geofencestatus",
    create_type=False,
)


def upgrade() -> None:
    geofence_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "geofence_asset_states",
        sa.Column("id_state", sa.Integer(), nullable=False),
        sa.Column("fence_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("current_status", geofence_status_enum, nullable=False),
        sa.Column("last_location_id", sa.Integer(), nullable=False),
        sa.Column("last_distance_to_boundary_meters", sa.Float(), nullable=True),
        sa.Column("last_accuracy", sa.Float(), nullable=True),
        sa.Column("first_detected_at", sa.DateTime(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fence_id"], ["geofences.id_geofence"]),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id_asset"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id_device"]),
        sa.ForeignKeyConstraint(["last_location_id"], ["locations.id_location"]),
        sa.PrimaryKeyConstraint("id_state"),
        sa.UniqueConstraint(
            "fence_id",
            "asset_id",
            name="uq_geofence_asset_state_fence_asset",
        ),
    )

    op.create_index(
        "idx_geofence_asset_states_asset_id",
        "geofence_asset_states",
        ["asset_id"],
    )

    op.create_index(
        "idx_geofence_asset_states_device_id",
        "geofence_asset_states",
        ["device_id"],
    )

    op.create_index(
        "idx_geofence_asset_states_status",
        "geofence_asset_states",
        ["current_status"],
    )
    


def downgrade() -> None:
    op.drop_index(
        "idx_geofence_asset_states_status",
        table_name="geofence_asset_states",
    )

    op.drop_index(
        "idx_geofence_asset_states_device_id",
        table_name="geofence_asset_states",
    )

    op.drop_index(
        "idx_geofence_asset_states_asset_id",
        table_name="geofence_asset_states",
    )

    op.drop_table("geofence_asset_states")

    geofence_status_enum.drop(op.get_bind(), checkfirst=True)
