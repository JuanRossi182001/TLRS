import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.integrations.chirpstack.binary_contract import (
    COMMAND_ACK_FPORT,
    LOCATION_UPLINK_FPORT,
    STATUS_UPLINK_FPORT,
)
from src.integrations.chirpstack.decoder import decode_up_event
from src.integrations.chirpstack.mqtt_topics import parse_chirpstack_event_topic
from src.integrations.chirpstack.payload_codec import (
    decode_command_ack_payload_v1,
    decode_status_payload_v1,
)
from src.integrations.chirpstack.schemas import (
    ChirpStackCommandAckUpEvent,
    ChirpStackNetworkAckEvent,
    ChirpStackTxAckEvent,
    ChirpStackUpEvent,
)
from src.models.chirpstack_event import ChirpStackEvent
from src.models.device import Device, DeviceState
from src.models.device_command import DeviceCommand, DeviceCommandStatus
from src.service.device_command_ack_service import DeviceCommandAckService
from src.service.location_ingestion_service import LocationIngestionService
from src.schemas.device_command_ack import DeviceCommandAckPayload


logger = logging.getLogger("chirpstack_event_service")


@dataclass(slots=True)
class ChirpStackHandleResult:
    success: bool
    event: ChirpStackEvent | None = None
    processed_kind: str | None = None
    device_id: int | None = None
    location_id: int | None = None
    command_uuid: str | None = None
    command_status: str | None = None
    command_status_changed: bool = False
    failure_reason: str | None = None


class ChirpStackEventService:
    DEVICE_UPLINK_LOCK_NAMESPACE = 6100

    def __init__(self, db: AsyncSession):
        self.db = db

    async def handle_event(self, topic: str, payload: dict) -> ChirpStackHandleResult:
        topic_info = parse_chirpstack_event_topic(topic)
        deduplication_id = payload.get("deduplicationId")

        if deduplication_id and await self._event_exists(deduplication_id):
            logger.info(
                "Skipping duplicate ChirpStack event. deduplication_id=%s topic=%s",
                deduplication_id,
                topic,
            )
            return ChirpStackHandleResult(
                success=True,
                processed_kind="duplicate",
            )

        event = ChirpStackEvent(
            event_type=topic_info.event_type,
            application_id=topic_info.application_id,
            dev_eui=topic_info.dev_eui,
            deduplication_id=deduplication_id,
            topic=topic,
            payload=payload,
            processed=False,
            error_message=None,
        )
        try:
            self.db.add(event)
            await self.db.flush()
            event_id = event.id
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            logger.info(
                "Skipping duplicate ChirpStack event after unique check. deduplication_id=%s topic=%s",
                deduplication_id,
                topic,
            )
            return ChirpStackHandleResult(
                success=True,
                processed_kind="duplicate",
            )

        if event_id is None:
            raise RuntimeError("ChirpStack event id was not assigned after flush")

        try:
            if topic_info.event_type == "up":
                result = await self._process_up_event(topic_info.application_id, topic_info.dev_eui, payload, event)
            elif topic_info.event_type == "join":
                result = await self._process_join_event(topic_info.dev_eui, event)
            elif topic_info.event_type == "log":
                result = await self._process_log_event(topic_info.dev_eui, event)
            elif topic_info.event_type == "txack":
                result = await self._process_txack_event(topic_info.dev_eui, payload, event)
            elif topic_info.event_type == "ack":
                result = await self._process_network_ack_event(topic_info.dev_eui, payload, event)
            else:
                event.error_message = f"Unsupported ChirpStack event type: {topic_info.event_type}"
                logger.warning(
                    "Unsupported ChirpStack event type. event_type=%s dev_eui=%s",
                    topic_info.event_type,
                    topic_info.dev_eui,
                )
                result = ChirpStackHandleResult(
                    success=False,
                    event=event,
                    processed_kind="unsupported",
                    failure_reason=event.error_message,
                )

            self.db.add(event)
            await self.db.commit()
            result.event = event
            return result
        except Exception as exc:
            await self.db.rollback()
            await self._mark_event_error(event_id, str(exc))
            return ChirpStackHandleResult(
                success=False,
                event=await self._get_event(event_id),
                processed_kind="error",
                failure_reason=str(exc),
            )

    async def _process_up_event(
        self,
        application_id: str,
        dev_eui: str,
        payload: dict,
        event: ChirpStackEvent,
    ) -> ChirpStackHandleResult:
        device = await self._get_device(dev_eui)
        if device is None:
            event.error_message = "Device not found or inactive for ChirpStack dev_eui"
            logger.warning(
                "ChirpStack device not found or inactive. application_id=%s dev_eui=%s",
                application_id,
                dev_eui,
            )
            return ChirpStackHandleResult(
                success=False,
                event=event,
                processed_kind="location",
                failure_reason=event.error_message,
            )

        up_event = self._validate_up_event(payload, dev_eui)
        event.device_id = device.id_device
        await self._acquire_device_uplink_lock(device.id_device)

        if device.chirpstack_application_id is None:
            device.chirpstack_application_id = application_id

        if device.chirpstack_device_profile_id is None:
            device.chirpstack_device_profile_id = up_event.deviceInfo.deviceProfileId

        if up_event.fPort == COMMAND_ACK_FPORT:
            return await self._process_application_ack_up_event(device, up_event, event)

        if up_event.fPort == STATUS_UPLINK_FPORT:
            return await self._process_status_up_event(device, up_event, event)

        if up_event.fPort != LOCATION_UPLINK_FPORT:
            event.error_message = f"Unsupported ChirpStack uplink fPort: {up_event.fPort}"
            return ChirpStackHandleResult(
                success=False,
                event=event,
                processed_kind="up",
                device_id=device.id_device,
                failure_reason=event.error_message,
            )

        normalized_telemetry = decode_up_event(up_event)

        location_service = LocationIngestionService(self.db)
        location = await location_service.persist_location(
            device=device,
            normalized_telemetry=normalized_telemetry,
            received_at=self._utcnow(),
        )

        event.processed = True
        event.error_message = None
        self.db.add(device)
        self.db.add(event)
        return ChirpStackHandleResult(
            success=True,
            event=event,
            processed_kind="location",
            device_id=device.id_device,
            location_id=location.id_location if location else None,
        )

    async def _process_status_up_event(
        self,
        device: Device,
        up_event: ChirpStackUpEvent,
        event: ChirpStackEvent,
    ) -> ChirpStackHandleResult:
        decode_status_payload_v1(up_event)

        device.state = DeviceState.ON
        device.last_seen_at = self._utcnow()
        event.processed = True
        event.error_message = None
        self.db.add(device)
        self.db.add(event)
        return ChirpStackHandleResult(
            success=True,
            event=event,
            processed_kind="status",
            device_id=device.id_device,
        )

    async def _process_join_event(
        self,
        dev_eui: str,
        event: ChirpStackEvent,
    ) -> ChirpStackHandleResult:
        device = await self._get_device(dev_eui)
        if device is not None:
            device.last_seen_at = self._utcnow()
            event.device_id = device.id_device
            self.db.add(device)

        event.processed = True
        event.error_message = None
        self.db.add(event)
        logger.info("ChirpStack join event processed. dev_eui=%s", dev_eui)
        return ChirpStackHandleResult(
            success=True,
            event=event,
            processed_kind="join",
            device_id=device.id_device if device is not None else None,
        )

    async def _process_log_event(
        self,
        dev_eui: str,
        event: ChirpStackEvent,
    ) -> ChirpStackHandleResult:
        device = await self._get_device(dev_eui)
        if device is not None:
            event.device_id = device.id_device

        event.processed = True
        event.error_message = None
        self.db.add(event)
        logger.info("ChirpStack log event processed. dev_eui=%s", dev_eui)
        return ChirpStackHandleResult(
            success=True,
            event=event,
            processed_kind="log",
            device_id=device.id_device if device is not None else None,
        )

    async def _process_application_ack_up_event(
        self,
        device: Device,
        up_event: ChirpStackUpEvent,
        event: ChirpStackEvent,
    ) -> ChirpStackHandleResult:
        try:
            ack_payload = self._build_command_ack_payload(device, up_event)
        except ValueError as exc:
            event.error_message = str(exc)
            return ChirpStackHandleResult(
                success=False,
                event=event,
                processed_kind="command_ack",
                device_id=device.id_device,
                failure_reason=event.error_message,
            )

        ack_service = DeviceCommandAckService(self.db)
        if ack_payload.command_id is not None:
            ack_result = await ack_service.process_ack(ack_payload)
        else:
            ack_result = await ack_service.process_ack_by_command_seq(
                device.id_device,
                ack_payload,
            )

        if not ack_result.success:
            event.error_message = ack_result.failure_reason or "COMMAND_ACK_PROCESSING_FAILED"
            logger.warning(
                "ChirpStack command ACK could not be applied. device_id=%s command_id=%s command_seq=%s reason=%s",
                device.id_device,
                ack_payload.command_id,
                ack_payload.command_seq,
                event.error_message,
            )
            return ChirpStackHandleResult(
                success=False,
                event=event,
                processed_kind="command_ack",
                device_id=device.id_device,
                command_uuid=ack_payload.command_id,
                failure_reason=event.error_message,
            )

        device.state = DeviceState.ON
        device.last_seen_at = self._utcnow()
        event.processed = True
        event.error_message = None
        self.db.add(device)
        self.db.add(event)
        return ChirpStackHandleResult(
            success=True,
            event=event,
            processed_kind="command_ack",
            device_id=device.id_device,
            command_uuid=(
                ack_result.command.command_uuid if ack_result.command is not None else ack_payload.command_id
            ),
            command_status=ack_result.command.status.value if ack_result.command else None,
            command_status_changed=(
                ack_result.command is not None
                and ack_result.previous_status != ack_result.command.status
            ),
        )

    def _build_command_ack_payload(
        self,
        device: Device,
        up_event: ChirpStackUpEvent,
        ) -> DeviceCommandAckPayload:
        if up_event.object is not None:
            try:
                ack_event = ChirpStackCommandAckUpEvent.model_validate(up_event.model_dump())
                if ack_event.deviceInfo.devEui != device.chirpstack_dev_eui:
                    raise ValueError("Payload devEui does not match topic dev_eui")
            except ValidationError as exc:
                raise ValueError(f"Invalid ChirpStack command ACK payload: {exc}") from exc

            return DeviceCommandAckPayload(
                command_id=ack_event.object.command_id,
                status=ack_event.object.status,
                executed_at=ack_event.object.executed_at,
                error_message=ack_event.object.error_message,
            )

        return decode_command_ack_payload_v1(up_event)

    async def _process_txack_event(
        self,
        dev_eui: str,
        payload: dict,
        event: ChirpStackEvent,
    ) -> ChirpStackHandleResult:
        device = await self._get_device(dev_eui)
        if device is None:
            event.error_message = "Device not found or inactive for ChirpStack dev_eui"
            return ChirpStackHandleResult(
                success=False,
                event=event,
                processed_kind="txack",
                failure_reason=event.error_message,
            )

        txack_event = ChirpStackTxAckEvent.model_validate(payload)
        command, resolution_error = await self._resolve_command_for_network_event(
            device_id=device.id_device,
            queue_item_id=txack_event.queueItemId,
            missing_queue_item_error="TXACK_QUEUE_ITEM_ID_MISSING",
            queue_item_not_found_error="TXACK_QUEUE_ITEM_NOT_FOUND",
        )
        if command is None:
            event.error_message = resolution_error
            logger.warning(
                "Ignoring ChirpStack txack without deterministic correlation. device_id=%s dev_eui=%s reason=%s",
                device.id_device,
                dev_eui,
                resolution_error,
            )
            return ChirpStackHandleResult(
                success=False,
                event=event,
                processed_kind="txack",
                device_id=device.id_device,
                failure_reason=event.error_message,
            )

        event.device_id = device.id_device
        previous_status = command.status
        if command.chirpstack_queue_item_id is None:
            command.chirpstack_queue_item_id = txack_event.queueItemId

        tx_status = (txack_event.status or "").strip().upper()
        tx_acked_at = self._normalize_datetime(txack_event.time) or self._utcnow()

        if not tx_status or tx_status == "OK":
            if command.tx_acked_at is None:
                command.tx_acked_at = tx_acked_at
            command.error_message = None
            event.processed = True
            event.error_message = None
        else:
            if command.status not in {
                DeviceCommandStatus.ACKED,
                DeviceCommandStatus.FAILED,
                DeviceCommandStatus.EXPIRED,
            }:
                command.status = DeviceCommandStatus.FAILED
                command.failed_at = self._utcnow()
            command.error_message = (
                f"LoRaWAN downlink transmission status was {tx_status}"
            )
            event.processed = True
            event.error_message = command.error_message
            logger.warning(
                "ChirpStack txack reported non-OK status. device_id=%s command_uuid=%s status=%s",
                device.id_device,
                command.command_uuid,
                tx_status,
            )

        self.db.add(command)
        self.db.add(event)
        return ChirpStackHandleResult(
            success=event.processed,
            event=event,
            processed_kind="txack",
            device_id=device.id_device,
            command_uuid=command.command_uuid,
            command_status=command.status.value,
            command_status_changed=(previous_status != command.status),
            failure_reason=event.error_message,
        )

    async def _process_network_ack_event(
        self,
        dev_eui: str,
        payload: dict,
        event: ChirpStackEvent,
    ) -> ChirpStackHandleResult:
        device = await self._get_device(dev_eui)
        if device is None:
            event.error_message = "Device not found or inactive for ChirpStack dev_eui"
            return ChirpStackHandleResult(
                success=False,
                event=event,
                processed_kind="ack",
                failure_reason=event.error_message,
            )

        ack_event = ChirpStackNetworkAckEvent.model_validate(payload)
        command, resolution_error = await self._resolve_command_for_network_event(
            device_id=device.id_device,
            queue_item_id=ack_event.queueItemId,
            missing_queue_item_error="LORAWAN_ACK_QUEUE_ITEM_ID_MISSING",
            queue_item_not_found_error="LORAWAN_ACK_QUEUE_ITEM_NOT_FOUND",
        )
        if command is None:
            event.error_message = resolution_error
            logger.warning(
                "Ignoring ChirpStack ack without deterministic correlation. device_id=%s dev_eui=%s reason=%s",
                device.id_device,
                dev_eui,
                resolution_error,
            )
            return ChirpStackHandleResult(
                success=False,
                event=event,
                processed_kind="ack",
                device_id=device.id_device,
                failure_reason=event.error_message,
            )

        event.device_id = device.id_device
        previous_status = command.status
        if command.chirpstack_queue_item_id is None:
            command.chirpstack_queue_item_id = ack_event.queueItemId

        if ack_event.acknowledged is True:
            command.lorawan_ack_at = self._normalize_datetime(ack_event.time) or self._utcnow()
            command.error_message = None
            event.processed = True
            event.error_message = None
        elif ack_event.acknowledged is False:
            if command.status not in {
                DeviceCommandStatus.ACKED,
                DeviceCommandStatus.FAILED,
                DeviceCommandStatus.EXPIRED,
            }:
                command.status = DeviceCommandStatus.FAILED
                command.failed_at = self._utcnow()
            command.error_message = "LoRaWAN downlink was not acknowledged"
            event.processed = True
            event.error_message = None
        else:
            event.processed = False
            event.error_message = "LORAWAN_ACK_ACKNOWLEDGED_FLAG_MISSING"

        self.db.add(command)
        self.db.add(event)
        return ChirpStackHandleResult(
            success=event.processed,
            event=event,
            processed_kind="ack",
            device_id=device.id_device,
            command_uuid=command.command_uuid,
            command_status=command.status.value,
            command_status_changed=(previous_status != command.status),
            failure_reason=event.error_message,
        )

    def _validate_up_event(self, payload: dict, dev_eui: str) -> ChirpStackUpEvent:
        try:
            up_event = ChirpStackUpEvent.model_validate(payload)
            if up_event.deviceInfo.devEui != dev_eui:
                raise ValueError("Payload devEui does not match topic dev_eui")
            return up_event
        except ValidationError as exc:
            raise ValueError(f"Invalid ChirpStack up payload: {exc}") from exc

    async def _event_exists(self, deduplication_id: str) -> bool:
        stmt = select(ChirpStackEvent.id).where(
            ChirpStackEvent.deduplication_id == deduplication_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _get_device(self, dev_eui: str) -> Device | None:
        stmt = select(Device).where(
            Device.chirpstack_dev_eui == dev_eui,
            Device.active.is_(True),
            Device.deleted == "N",
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _resolve_command_for_network_event(
        self,
        device_id: int,
        queue_item_id: str | None,
        missing_queue_item_error: str,
        queue_item_not_found_error: str,
    ) -> tuple[DeviceCommand | None, str | None]:
        if not queue_item_id:
            return None, missing_queue_item_error

        command = await self._get_command_by_queue_item_id(queue_item_id)
        if command is not None:
            if command.device_id != device_id:
                return None, queue_item_not_found_error
            return command, None

        return None, queue_item_not_found_error

    async def _get_command_by_queue_item_id(
        self,
        queue_item_id: str,
    ) -> DeviceCommand | None:
        stmt = (
            select(DeviceCommand)
            .where(DeviceCommand.chirpstack_queue_item_id == queue_item_id)
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _acquire_device_uplink_lock(self, device_id: int) -> None:
        stmt = select(
            func.pg_advisory_xact_lock(
                self.DEVICE_UPLINK_LOCK_NAMESPACE,
                device_id,
            )
        )
        await self.db.execute(stmt)

    async def _mark_event_error(self, event_id: int, error_message: str) -> None:
        event = await self._get_event(event_id)
        if event is None:
            return

        event.processed = False
        event.error_message = error_message[:500]
        self.db.add(event)
        await self.db.commit()

    async def _get_event(self, event_id: int) -> ChirpStackEvent | None:
        stmt = select(ChirpStackEvent).where(ChirpStackEvent.id == event_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    def _normalize_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None

        if value.tzinfo is None:
            return value

        return value.astimezone(UTC).replace(tzinfo=None)

    def _utcnow(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
