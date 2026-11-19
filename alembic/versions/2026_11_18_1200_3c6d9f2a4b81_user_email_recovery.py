"""Add email verification and password recovery tokens.

Revision ID: 3c6d9f2a4b81
Revises: e7c1a9d5b2f4
Create Date: 2026-11-18 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3c6d9f2a4b81"
down_revision: Union[str, Sequence[str], None] = "e7c1a9d5b2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "email_verification_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "user_email_tokens",
        sa.Column("id_token", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id_user"]),
    )
    op.create_index("ix_user_email_tokens_user_id", "user_email_tokens", ["user_id"])
    op.create_index(
        "ix_user_email_tokens_token_hash",
        "user_email_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_user_email_tokens_created_at",
        "user_email_tokens",
        ["created_at"],
    )
    op.create_index(
        "ix_user_email_tokens_expires_at",
        "user_email_tokens",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_email_tokens_expires_at", table_name="user_email_tokens")
    op.drop_index("ix_user_email_tokens_created_at", table_name="user_email_tokens")
    op.drop_index("ix_user_email_tokens_token_hash", table_name="user_email_tokens")
    op.drop_index("ix_user_email_tokens_user_id", table_name="user_email_tokens")
    op.drop_table("user_email_tokens")
    op.drop_column("users", "email_verification_required")
    op.drop_column("users", "email_verified_at")
