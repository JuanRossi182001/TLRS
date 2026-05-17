"""add rbac tables

Revision ID: 6f0d9d3a4b21
Revises: 10718bead5ab
Create Date: 2026-05-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6f0d9d3a4b21"
down_revision: Union[str, Sequence[str], None] = "10718bead5ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("id_user", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password", sa.String(), nullable=False),
        sa.Column("deleted", sa.String(length=1), nullable=False),
        sa.Column("id_client", sa.Integer(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["id_client"], ["clients.id_client"]),
        sa.PrimaryKeyConstraint("id_user"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "roles",
        sa.Column("id_role", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("deleted", sa.String(length=1), nullable=False),
        sa.PrimaryKeyConstraint("id_role"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "services",
        sa.Column("id_service", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("deleted", sa.String(length=1), nullable=False),
        sa.PrimaryKeyConstraint("id_service"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "user_roles",
        sa.Column("id_user_role", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("deleted", sa.String(length=1), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id_role"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id_user"]),
        sa.PrimaryKeyConstraint("id_user_role"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    )
    op.create_table(
        "service_roles",
        sa.Column("id_service_role", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("deleted", sa.String(length=1), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id_role"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id_service"]),
        sa.PrimaryKeyConstraint("id_service_role"),
        sa.UniqueConstraint(
            "service_id",
            "role_id",
            name="uq_service_roles_service_role",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("service_roles")
    op.drop_table("user_roles")
    op.drop_table("services")
    op.drop_table("roles")
    op.drop_table("users")
