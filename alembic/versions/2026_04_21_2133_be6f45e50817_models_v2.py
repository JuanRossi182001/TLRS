"""models v2

Revision ID: be6f45e50817
Revises: e164566bafe4
Create Date: 2026-04-21 21:33:46.113215

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'be6f45e50817'
down_revision: Union[str, Sequence[str], None] = 'e164566bafe4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


asset_status_enum = postgresql.ENUM('ACTIVE', 'INACTIVE', name='assetstatus')
credential_status_enum = postgresql.ENUM('ACTIVE', 'REVOKED', name='credentialstatus')
device_protocol_enum = postgresql.ENUM('HTTP', 'MQTT', name='devicecommunicationprotocol')
old_device_protocol_enum = postgresql.ENUM('HTTP', 'MQTT', name='devicecomunicationprotocol')


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    asset_status_enum.create(bind, checkfirst=True)
    credential_status_enum.create(bind, checkfirst=True)
    device_protocol_enum.create(bind, checkfirst=True)

    op.alter_column('assets', 'type_aseet',
               existing_type=sa.VARCHAR(),
               new_column_name='asset_type',
               existing_nullable=False)
    op.alter_column('assets', 'serial',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.execute("""
        ALTER TABLE assets
        ALTER COLUMN status TYPE assetstatus
        USING (
            CASE status
                WHEN 'A' THEN 'ACTIVE'
                WHEN 'I' THEN 'INACTIVE'
                ELSE status
            END
        )::assetstatus
    """)
    op.execute("""
        ALTER TABLE device_credentials
        ALTER COLUMN status TYPE credentialstatus
        USING (
            CASE status
                WHEN 'A' THEN 'ACTIVE'
                WHEN 'R' THEN 'REVOKED'
                ELSE status
            END
        )::credentialstatus
    """)
    op.alter_column('devices', 'comunication_protocol',
               existing_type=old_device_protocol_enum,
               new_column_name='communication_protocol',
               existing_nullable=False)
    op.execute("""
        ALTER TABLE devices
        ALTER COLUMN communication_protocol TYPE devicecommunicationprotocol
        USING communication_protocol::text::devicecommunicationprotocol
    """)
    op.alter_column('devices', 'serial',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.alter_column('devices', 'name',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.alter_column('devices', 'type',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.alter_column('devices', 'active',
               existing_type=sa.BOOLEAN(),
               nullable=False)
    op.alter_column('locations', 'lat',
               existing_type=sa.VARCHAR(),
               new_column_name='latitude',
               existing_nullable=False)
    op.alter_column('locations', 'long',
               existing_type=sa.VARCHAR(),
               new_column_name='longitude',
               existing_nullable=False)
    op.alter_column('locations', 'accuarcy',
               existing_type=sa.VARCHAR(),
               new_column_name='accuracy',
               existing_nullable=False)
    op.add_column('locations', sa.Column('device_timestamp', sa.DateTime(), nullable=True))
    op.add_column('locations', sa.Column('received_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False))
    op.alter_column('locations', 'latitude',
               existing_type=sa.VARCHAR(),
               type_=sa.Float(),
               existing_nullable=False,
               postgresql_using='latitude::double precision')
    op.alter_column('locations', 'longitude',
               existing_type=sa.VARCHAR(),
               type_=sa.Float(),
               existing_nullable=False,
               postgresql_using='longitude::double precision')
    op.alter_column('locations', 'accuracy',
               existing_type=sa.VARCHAR(),
               type_=sa.Float(),
               nullable=True,
               postgresql_using='accuracy::double precision')
    op.alter_column('locations', 'altitude',
               existing_type=sa.VARCHAR(),
               type_=sa.Float(),
               nullable=True,
               postgresql_using='altitude::double precision')
    op.alter_column('locations', 'geometry',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.alter_column('locations', 'received_at',
               existing_type=sa.DateTime(),
               server_default=None)
    op.alter_column('telemetry_messages', 'recived_at',
               existing_type=sa.DateTime(),
               new_column_name='received_at',
               existing_nullable=False)
    op.alter_column('telemetry_messages', 'raw_payload',
               existing_type=sa.VARCHAR(),
               type_=sa.Text(),
               existing_nullable=False)
    op.execute("""
        ALTER TABLE telemetry_messages
        ALTER COLUMN protocol TYPE devicecommunicationprotocol
        USING protocol::text::devicecommunicationprotocol
    """)
    op.alter_column('telemetry_messages', 'source_ip',
               existing_type=sa.VARCHAR(),
               nullable=True)
    old_device_protocol_enum.drop(bind, checkfirst=True)


def downgrade() -> None:
    """Downgrade schema."""
    old_device_protocol_enum.create(op.get_bind(), checkfirst=True)

    op.alter_column('telemetry_messages', 'received_at',
               existing_type=sa.DateTime(),
               new_column_name='recived_at',
               existing_nullable=False)
    op.alter_column('telemetry_messages', 'source_ip',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.execute("""
        ALTER TABLE telemetry_messages
        ALTER COLUMN protocol TYPE devicecomunicationprotocol
        USING protocol::text::devicecomunicationprotocol
    """)
    op.alter_column('telemetry_messages', 'raw_payload',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(),
               existing_nullable=False)
    op.alter_column('locations', 'geometry',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.alter_column('locations', 'altitude',
               existing_type=sa.Float(),
               type_=sa.VARCHAR(),
               nullable=False)
    op.alter_column('locations', 'accuracy',
               existing_type=sa.Float(),
               type_=sa.VARCHAR(),
               nullable=False)
    op.alter_column('locations', 'longitude',
               existing_type=sa.Float(),
               type_=sa.VARCHAR(),
               existing_nullable=False)
    op.alter_column('locations', 'latitude',
               existing_type=sa.Float(),
               type_=sa.VARCHAR(),
               existing_nullable=False)
    op.drop_column('locations', 'received_at')
    op.drop_column('locations', 'device_timestamp')
    op.alter_column('locations', 'accuracy',
               existing_type=sa.VARCHAR(),
               new_column_name='accuarcy',
               existing_nullable=False)
    op.alter_column('locations', 'longitude',
               existing_type=sa.VARCHAR(),
               new_column_name='long',
               existing_nullable=False)
    op.alter_column('locations', 'latitude',
               existing_type=sa.VARCHAR(),
               new_column_name='lat',
               existing_nullable=False)
    op.alter_column('devices', 'active',
               existing_type=sa.BOOLEAN(),
               nullable=True)
    op.alter_column('devices', 'type',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.alter_column('devices', 'name',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.alter_column('devices', 'serial',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.execute("""
        ALTER TABLE devices
        ALTER COLUMN communication_protocol TYPE devicecomunicationprotocol
        USING communication_protocol::text::devicecomunicationprotocol
    """)
    op.alter_column('devices', 'communication_protocol',
               existing_type=old_device_protocol_enum,
               new_column_name='comunication_protocol',
               existing_nullable=False)
    op.execute("""
        ALTER TABLE device_credentials
        ALTER COLUMN status TYPE varchar(1)
        USING (
            CASE status::text
                WHEN 'ACTIVE' THEN 'A'
                WHEN 'REVOKED' THEN 'R'
                ELSE status::text
            END
        )::varchar(1)
    """)
    op.execute("""
        ALTER TABLE assets
        ALTER COLUMN status TYPE varchar(1)
        USING (
            CASE status::text
                WHEN 'ACTIVE' THEN 'A'
                WHEN 'INACTIVE' THEN 'I'
                ELSE status::text
            END
        )::varchar(1)
    """)
    op.alter_column('assets', 'serial',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.alter_column('assets', 'asset_type',
               existing_type=sa.VARCHAR(),
               new_column_name='type_aseet',
               existing_nullable=False)

    device_protocol_enum.drop(op.get_bind(), checkfirst=True)
    credential_status_enum.drop(op.get_bind(), checkfirst=True)
    asset_status_enum.drop(op.get_bind(), checkfirst=True)
