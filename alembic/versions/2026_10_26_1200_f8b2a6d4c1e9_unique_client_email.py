"""enforce unique email for active clients

Revision ID: f8b2a6d4c1e9
Revises: d2a4f6c8e0b1
Create Date: 2026-10-26 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8b2a6d4c1e9"
down_revision: Union[str, Sequence[str], None] = "d2a4f6c8e0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            """
            SELECT lower(email) AS normalized_email, array_agg(id_client) AS client_ids
            FROM clients
            WHERE deleted = 'N'
            GROUP BY lower(email)
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot enforce active client email uniqueness: duplicate email "
            f"{duplicate.normalized_email!r} exists for client IDs "
            f"{duplicate.client_ids}. Resolve these rows and retry the migration."
        )

    op.create_index(
        "uq_clients_email_active_ci",
        "clients",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("deleted = 'N'"),
    )


def downgrade() -> None:
    op.drop_index("uq_clients_email_active_ci", table_name="clients")
