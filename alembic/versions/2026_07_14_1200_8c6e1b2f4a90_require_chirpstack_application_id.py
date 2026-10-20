"""require chirpstack application id

Revision ID: 8c6e1b2f4a90
Revises: 2ab4c6d8e9f1
Create Date: 2026-07-14 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c6e1b2f4a90"
down_revision: Union[str, Sequence[str], None] = "2ab4c6d8e9f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = "ck_devices_chirpstack_requires_application_id"
CONSTRAINT_SQL = (
    "communication_protocol != 'CHIRPSTACK' "
    "OR (chirpstack_application_id IS NOT NULL AND btrim(chirpstack_application_id) <> '')"
)


def upgrade() -> None:
    bind = op.get_bind()
    invalid_rows = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM devices
            WHERE communication_protocol = 'CHIRPSTACK'
              AND (
                  chirpstack_application_id IS NULL
                  OR btrim(chirpstack_application_id) = ''
              )
            """
        )
    ).scalar_one()

    if invalid_rows:
        raise RuntimeError(
            "Cannot enforce ChirpStack application_id requirement while devices "
            f"without chirpstack_application_id still exist: {invalid_rows}. "
            "Delete or fix those devices before running this migration."
        )

    op.create_check_constraint(
        CONSTRAINT_NAME,
        "devices",
        CONSTRAINT_SQL,
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "devices", type_="check")
