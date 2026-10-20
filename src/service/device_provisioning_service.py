import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.integrations.chirpstack.api_client import (
    ChirpStackAlreadyExistsError,
    ChirpStackApiClient,
    ChirpStackApiError,
    ChirpStackDeviceRecord,
    ChirpStackNotFoundError,
)
from src.models.device import (
    Device,
    DeviceCommunicationProtocol,
    DeviceProvisioningStatus,
    DeviceState,
)
from src.models.asset import Asset, AssetStatus
from src.models.client import Client
from src.schemas.device import ChirpStackProvisioningRead, ProvisioningAssetCreate
from src.service.device_assignment_service import (
    DeviceAssignmentError,
    DeviceAssignmentService,
)


logger = logging.getLogger("device_provisioning_service")


class DeviceProvisioningError(ValueError):
    pass


class DeviceProvisioningConflictError(DeviceProvisioningError):
    pass


class DeviceProvisioningNotFoundError(DeviceProvisioningError):
    pass


class DeviceProvisioningService:
    def __init__(
        self,
        db: AsyncSession,
        chirpstack_api_client: ChirpStackApiClient | None = None,
    ):
        self.db = db
        self.chirpstack_api_client = chirpstack_api_client or ChirpStackApiClient()

    async def provision_device(
        self,
        *,
        serial: str,
        name: str,
        type: str,
        dev_eui: str,
        join_eui: str,
        app_key: str,
        chirpstack_application_id: str,
        chirpstack_device_profile_id: str,
        client_id: int,
        asset_id: int | None = None,
        asset: ProvisioningAssetCreate | None = None,
        communication_protocol: DeviceCommunicationProtocol = DeviceCommunicationProtocol.CHIRPSTACK,
        description: str | None = None,
        is_disabled: bool = False,
    ) -> ChirpStackProvisioningRead:
        if communication_protocol != DeviceCommunicationProtocol.CHIRPSTACK:
            raise DeviceProvisioningError(
                "Only CHIRPSTACK device provisioning is supported"
            )

        resolved_asset = await self._resolve_asset(
            client_id=client_id,
            asset_id=asset_id,
            asset=asset,
        )

        device = Device(
            serial=serial,
            name=name,
            type=type,
            state=DeviceState.OFF,
            communication_protocol=DeviceCommunicationProtocol.CHIRPSTACK,
            client_id=client_id,
            active=True,
            chirpstack_dev_eui=dev_eui,
            join_eui=join_eui,
            chirpstack_application_id=chirpstack_application_id,
            chirpstack_device_profile_id=chirpstack_device_profile_id,
            provisioning_status=DeviceProvisioningStatus.PENDING.value,
            provisioning_error=None,
        )

        try:
            device = await DeviceAssignmentService(self.db).create_initial_assignment(
                device,
                resolved_asset,
            )
        except DeviceAssignmentError as exc:
            raise DeviceProvisioningConflictError(str(exc)) from exc

        try:
            await self._upsert_remote_device(
                device=device,
                description=description,
                is_disabled=is_disabled,
            )
            await self._ensure_remote_keys(device=device, app_key=app_key, allow_update=True)
        except (DeviceProvisioningError, ChirpStackApiError) as exc:
            await self._mark_failed(device, str(exc), app_key=app_key)
            raise

        await self._mark_provisioned(device, app_key_last4=app_key[-4:])
        return self._build_provisioning_read(device)

    async def retry_provisioning(
        self,
        *,
        device_id: int,
        app_key: str | None = None,
    ) -> ChirpStackProvisioningRead:
        device = await self._get_device(device_id)
        if device is None:
            raise DeviceProvisioningNotFoundError("Device not found.")

        self._validate_retryable_device(device)

        device.provisioning_status = DeviceProvisioningStatus.PENDING.value
        device.provisioning_error = None
        self.db.add(device)
        await self.db.commit()
        await self.db.refresh(device)

        try:
            await self._upsert_remote_device(
                device=device,
                description=None,
                is_disabled=None,
            )
            await self._ensure_remote_keys(
                device=device,
                app_key=app_key,
                allow_update=app_key is not None,
            )
        except (DeviceProvisioningError, ChirpStackApiError) as exc:
            await self._mark_failed(device, str(exc), app_key=app_key)
            raise

        await self._mark_provisioned(
            device,
            app_key_last4=app_key[-4:] if app_key is not None else device.app_key_last4,
        )
        return self._build_provisioning_read(device)

    async def get_provisioning(self, device_id: int) -> ChirpStackProvisioningRead:
        device = await self._get_device(device_id)
        if device is None:
            raise DeviceProvisioningNotFoundError("Device not found.")
        return self._build_provisioning_read(device)

    async def _upsert_remote_device(
        self,
        *,
        device: Device,
        description: str | None,
        is_disabled: bool | None,
    ) -> None:
        try:
            self.chirpstack_api_client.create_device(
                dev_eui=self._require_field(device.chirpstack_dev_eui, "dev_eui"),
                name=self._require_field(device.name, "name"),
                application_id=self._require_field(
                    device.chirpstack_application_id,
                    "chirpstack_application_id",
                ),
                device_profile_id=self._require_field(
                    device.chirpstack_device_profile_id,
                    "chirpstack_device_profile_id",
                ),
                join_eui=self._require_field(device.join_eui, "join_eui"),
                description=description,
                is_disabled=bool(is_disabled),
                tags={"serial": device.serial},
            )
            return
        except ChirpStackAlreadyExistsError:
            remote_device = self.chirpstack_api_client.get_device(
                self._require_field(device.chirpstack_dev_eui, "dev_eui")
            )

        self._validate_remote_device_compatibility(device, remote_device)
        resolved_description = (
            description if description is not None else remote_device.description
        )
        resolved_is_disabled = (
            is_disabled if is_disabled is not None else remote_device.is_disabled
        )
        self.chirpstack_api_client.update_device(
            dev_eui=self._require_field(device.chirpstack_dev_eui, "dev_eui"),
            name=self._require_field(device.name, "name"),
            application_id=self._require_field(
                device.chirpstack_application_id,
                "chirpstack_application_id",
            ),
            device_profile_id=self._require_field(
                device.chirpstack_device_profile_id,
                "chirpstack_device_profile_id",
            ),
            join_eui=self._require_field(device.join_eui, "join_eui"),
            description=resolved_description,
            is_disabled=resolved_is_disabled,
            tags={"serial": device.serial},
        )

    async def _ensure_remote_keys(
        self,
        *,
        device: Device,
        app_key: str | None,
        allow_update: bool,
    ) -> None:
        dev_eui = self._require_field(device.chirpstack_dev_eui, "dev_eui")

        if app_key is None:
            try:
                self.chirpstack_api_client.get_device_keys(dev_eui)
                return
            except ChirpStackNotFoundError as exc:
                raise DeviceProvisioningError(
                    "app_key is required to provision missing ChirpStack OTAA keys"
                ) from exc

        try:
            self.chirpstack_api_client.create_device_keys(dev_eui=dev_eui, app_key=app_key)
            return
        except ChirpStackAlreadyExistsError:
            if not allow_update:
                return

        self.chirpstack_api_client.update_device_keys(dev_eui=dev_eui, app_key=app_key)

    async def _mark_failed(
        self,
        device: Device,
        error_message: str,
        *,
        app_key: str | None,
    ) -> None:
        sanitized_error = self._sanitize_error_message(error_message, app_key=app_key)
        logger.warning(
            "ChirpStack provisioning failed. device_id=%s dev_eui=%s reason=%s",
            device.id_device,
            device.chirpstack_dev_eui,
            sanitized_error,
        )

        device.provisioning_status = DeviceProvisioningStatus.FAILED.value
        device.provisioned_at = None
        device.provisioning_error = sanitized_error
        self.db.add(device)
        await self.db.commit()
        await self.db.refresh(device)

    async def _mark_provisioned(
        self,
        device: Device,
        *,
        app_key_last4: str | None,
    ) -> None:
        device.provisioning_status = DeviceProvisioningStatus.PROVISIONED.value
        device.provisioned_at = self._utcnow()
        device.provisioning_error = None
        if app_key_last4 is not None:
            device.app_key_last4 = app_key_last4
        self.db.add(device)
        await self.db.commit()
        await self.db.refresh(device)

    async def _get_device(self, device_id: int) -> Device | None:
        stmt = select(Device).where(
            Device.id_device == device_id,
            Device.deleted == "N",
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _resolve_asset(
        self,
        *,
        client_id: int,
        asset_id: int | None,
        asset: ProvisioningAssetCreate | None,
    ) -> Asset:
        if (asset_id is None) == (asset is None):
            raise DeviceProvisioningError("Exactly one of asset_id or asset is required")

        await self._validate_client(client_id)

        if asset is not None:
            if asset.status != AssetStatus.ACTIVE:
                raise DeviceProvisioningError(
                    "A newly provisioned device requires an active asset"
                )
            created_asset = Asset(
                asset_type=asset.asset_type,
                serial=asset.serial,
                client_id=client_id,
                status=asset.status,
                deleted="N",
            )
            self.db.add(created_asset)
            await self.db.flush()
            return created_asset

        result = await self.db.execute(
            select(Asset).where(
                Asset.id_asset == asset_id,
                Asset.client_id == client_id,
                Asset.deleted == "N",
            )
        )
        existing_asset = result.scalar_one_or_none()
        if existing_asset is None:
            raise DeviceProvisioningNotFoundError("Asset not found for this client.")
        if existing_asset.status != AssetStatus.ACTIVE:
            raise DeviceProvisioningConflictError("Asset is inactive.")

        return existing_asset

    async def _validate_client(self, client_id: int) -> None:
        result = await self.db.execute(
            select(Client.id_client).where(
                Client.id_client == client_id,
                Client.deleted == "N",
            )
        )
        if result.scalar_one_or_none() is None:
            raise DeviceProvisioningNotFoundError("Client not found.")

    def _validate_remote_device_compatibility(
        self,
        device: Device,
        remote_device: ChirpStackDeviceRecord,
    ) -> None:
        expected_application_id = self._require_field(
            device.chirpstack_application_id,
            "chirpstack_application_id",
        )
        expected_profile_id = self._require_field(
            device.chirpstack_device_profile_id,
            "chirpstack_device_profile_id",
        )

        if remote_device.application_id != expected_application_id:
            raise DeviceProvisioningConflictError(
                "Existing ChirpStack device belongs to a different application_id"
            )

        if remote_device.device_profile_id != expected_profile_id:
            raise DeviceProvisioningConflictError(
                "Existing ChirpStack device belongs to a different device_profile_id"
            )

    def _validate_retryable_device(self, device: Device) -> None:
        if device.communication_protocol != DeviceCommunicationProtocol.CHIRPSTACK:
            raise DeviceProvisioningError(
                "Only CHIRPSTACK devices can be retried through this endpoint"
            )

        if device.provisioning_status == DeviceProvisioningStatus.PROVISIONED.value:
            raise DeviceProvisioningConflictError("Device is already provisioned.")

        self._require_field(device.chirpstack_dev_eui, "dev_eui")
        self._require_field(device.join_eui, "join_eui")
        self._require_field(device.chirpstack_application_id, "chirpstack_application_id")
        self._require_field(
            device.chirpstack_device_profile_id,
            "chirpstack_device_profile_id",
        )

    def _require_field(self, value: str | None, field_name: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise DeviceProvisioningError(f"{field_name} is required for provisioning")
        return normalized

    def _sanitize_error_message(self, message: str, *, app_key: str | None) -> str:
        sanitized = message.strip()
        if app_key:
            sanitized = sanitized.replace(app_key, "[REDACTED]")
        return sanitized[:500]

    def _build_provisioning_read(self, device: Device) -> ChirpStackProvisioningRead:
        return ChirpStackProvisioningRead(
            id_device=device.id_device,
            serial=device.serial,
            dev_eui=device.chirpstack_dev_eui,
            join_eui=device.join_eui,
            chirpstack_application_id=device.chirpstack_application_id,
            chirpstack_device_profile_id=device.chirpstack_device_profile_id,
            provisioning_status=DeviceProvisioningStatus(device.provisioning_status),
            provisioned_at=device.provisioned_at,
            provisioning_error=device.provisioning_error,
            app_key_last4=device.app_key_last4,
        )

    def _utcnow(self):
        return datetime.now(UTC).replace(tzinfo=None)
