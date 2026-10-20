from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.settings import settings


class ChirpStackApiError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


class ChirpStackApiConfigurationError(ChirpStackApiError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ChirpStackAuthError(ChirpStackApiError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ChirpStackApiAuthenticationError(ChirpStackAuthError):
    pass


class ChirpStackApiPermissionDeniedError(ChirpStackAuthError):
    def __init__(self, message: str):
        super().__init__(message)


class ChirpStackUnavailableError(ChirpStackApiError):
    def __init__(self, message: str):
        super().__init__(message, retryable=True)


class ChirpStackApiTimeoutError(ChirpStackUnavailableError):
    def __init__(self, message: str):
        super().__init__(message)


class ChirpStackApiConnectionError(ChirpStackUnavailableError):
    def __init__(self, message: str):
        super().__init__(message)


class ChirpStackNotFoundError(ChirpStackApiError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ChirpStackAlreadyExistsError(ChirpStackApiError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ChirpStackValidationError(ChirpStackApiError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ChirpStackApiRequestError(ChirpStackApiError):
    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message, retryable=retryable)


@dataclass(slots=True, frozen=True)
class ChirpStackDeviceRecord:
    dev_eui: str
    name: str
    application_id: str
    device_profile_id: str
    description: str | None
    join_eui: str | None
    is_disabled: bool
    tags: dict[str, str]


@dataclass(slots=True, frozen=True)
class ChirpStackDeviceKeysRecord:
    dev_eui: str
    nwk_key: str | None
    app_key: str | None


class ChirpStackApiClient:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        token: str | None = None,
        use_tls: bool | None = None,
        timeout_seconds: int | None = None,
    ):
        self.host = (host or settings.chirpstack_api_host).strip()
        self.port = port or settings.chirpstack_api_port
        self.token = (token or settings.chirpstack_api_token or "").strip()
        self.use_tls = (
            settings.chirpstack_api_use_tls if use_tls is None else use_tls
        )
        self.timeout_seconds = (
            timeout_seconds or settings.chirpstack_api_timeout_seconds
        )

    def enqueue_downlink(
        self,
        dev_eui: str,
        f_port: int,
        data: bytes,
        confirmed: bool,
        expires_at: datetime | None = None,
    ) -> str:
        _, api, timestamp_class = self._load_grpc_dependencies()
        self._validate_configuration("gRPC downlinks")

        normalized_dev_eui = self._normalize_eui(
            dev_eui,
            field_name="dev_eui",
        )

        if f_port <= 0:
            raise ChirpStackApiConfigurationError("ChirpStack f_port must be greater than 0")

        if not data:
            raise ChirpStackApiConfigurationError("ChirpStack downlink data must not be empty")

        request = api.EnqueueDeviceQueueItemRequest()
        request.queue_item.dev_eui = normalized_dev_eui
        request.queue_item.confirmed = confirmed
        request.queue_item.f_port = f_port
        request.queue_item.data = data

        if expires_at is not None:
            expires_at_proto = timestamp_class()
            expires_at_proto.FromDatetime(self._normalize_datetime(expires_at))
            request.queue_item.expires_at.CopyFrom(expires_at_proto)

        response = self._call_device_service(
            rpc_name="Enqueue",
            request=request,
            operation_name="enqueue",
        )

        if not response.id:
            raise ChirpStackApiRequestError(
                "ChirpStack enqueue succeeded without returning a queue item id",
                retryable=False,
            )

        return response.id

    def get_device(self, dev_eui: str) -> ChirpStackDeviceRecord:
        _, api, _ = self._load_grpc_dependencies()
        self._validate_configuration("device lookup")

        request = api.GetDeviceRequest()
        request.dev_eui = self._normalize_eui(dev_eui, field_name="dev_eui")
        response = self._call_device_service(
            rpc_name="Get",
            request=request,
            operation_name="get device",
        )
        return self._build_device_record(response.device)

    def create_device(
        self,
        *,
        dev_eui: str,
        name: str,
        application_id: str,
        device_profile_id: str,
        join_eui: str,
        description: str | None = None,
        is_disabled: bool = False,
        tags: dict[str, str] | None = None,
    ) -> None:
        _, api, _ = self._load_grpc_dependencies()
        self._validate_configuration("device provisioning")

        request = api.CreateDeviceRequest()
        self._populate_device_message(
            device=request.device,
            dev_eui=dev_eui,
            name=name,
            application_id=application_id,
            device_profile_id=device_profile_id,
            join_eui=join_eui,
            description=description,
            is_disabled=is_disabled,
            tags=tags,
        )
        self._call_device_service(
            rpc_name="Create",
            request=request,
            operation_name="create device",
        )

    def update_device(
        self,
        *,
        dev_eui: str,
        name: str,
        application_id: str,
        device_profile_id: str,
        join_eui: str,
        description: str | None = None,
        is_disabled: bool = False,
        tags: dict[str, str] | None = None,
    ) -> None:
        _, api, _ = self._load_grpc_dependencies()
        self._validate_configuration("device provisioning")

        request = api.UpdateDeviceRequest()
        self._populate_device_message(
            device=request.device,
            dev_eui=dev_eui,
            name=name,
            application_id=application_id,
            device_profile_id=device_profile_id,
            join_eui=join_eui,
            description=description,
            is_disabled=is_disabled,
            tags=tags,
        )
        self._call_device_service(
            rpc_name="Update",
            request=request,
            operation_name="update device",
        )

    def get_device_keys(self, dev_eui: str) -> ChirpStackDeviceKeysRecord:
        _, api, _ = self._load_grpc_dependencies()
        self._validate_configuration("device keys lookup")

        request = api.GetDeviceKeysRequest()
        request.dev_eui = self._normalize_eui(dev_eui, field_name="dev_eui")
        response = self._call_device_service(
            rpc_name="GetKeys",
            request=request,
            operation_name="get device keys",
        )
        return ChirpStackDeviceKeysRecord(
            dev_eui=response.device_keys.dev_eui,
            nwk_key=response.device_keys.nwk_key or None,
            app_key=response.device_keys.app_key or None,
        )

    def create_device_keys(self, *, dev_eui: str, app_key: str) -> None:
        _, api, _ = self._load_grpc_dependencies()
        self._validate_configuration("device keys provisioning")

        request = api.CreateDeviceKeysRequest()
        self._populate_device_keys_message(
            device_keys=request.device_keys,
            dev_eui=dev_eui,
            app_key=app_key,
        )
        self._call_device_service(
            rpc_name="CreateKeys",
            request=request,
            operation_name="create device keys",
        )

    def update_device_keys(self, *, dev_eui: str, app_key: str) -> None:
        _, api, _ = self._load_grpc_dependencies()
        self._validate_configuration("device keys provisioning")

        request = api.UpdateDeviceKeysRequest()
        self._populate_device_keys_message(
            device_keys=request.device_keys,
            dev_eui=dev_eui,
            app_key=app_key,
        )
        self._call_device_service(
            rpc_name="UpdateKeys",
            request=request,
            operation_name="update device keys",
        )

    def _build_channel(self) -> Any:
        grpc, _, _ = self._load_grpc_dependencies()
        target = f"{self.host}:{self.port}"
        if self.use_tls:
            return grpc.secure_channel(target, grpc.ssl_channel_credentials())
        return grpc.insecure_channel(target)

    def _metadata(self) -> list[tuple[str, str]]:
        return [("authorization", f"Bearer {self.token}")]

    def _call_device_service(
        self,
        *,
        rpc_name: str,
        request: Any,
        operation_name: str,
    ) -> Any:
        grpc, api, _ = self._load_grpc_dependencies()
        channel = self._build_channel()
        try:
            client = api.DeviceServiceStub(channel)
            rpc = getattr(client, rpc_name)
            return rpc(
                request,
                metadata=self._metadata(),
                timeout=self.timeout_seconds,
            )
        except grpc.FutureTimeoutError as exc:
            raise ChirpStackApiTimeoutError(
                f"ChirpStack {operation_name} timed out after {self.timeout_seconds} seconds"
            ) from exc
        except grpc.RpcError as exc:
            raise self._map_rpc_error(exc, operation_name=operation_name) from exc
        except Exception as exc:
            raise ChirpStackApiConnectionError(
                f"ChirpStack {operation_name} failed: {exc}"
            ) from exc
        finally:
            channel.close()

    def _map_rpc_error(self, exc: Any, *, operation_name: str) -> ChirpStackApiError:
        grpc, _, _ = self._load_grpc_dependencies()
        status_code = exc.code()
        details = (exc.details() or "Unknown gRPC error").strip()
        details = self._augment_connectivity_hint(details)

        if status_code == grpc.StatusCode.UNAUTHENTICATED:
            return ChirpStackApiAuthenticationError(
                f"ChirpStack API authentication failed during {operation_name}: {details}"
            )

        if status_code == grpc.StatusCode.PERMISSION_DENIED:
            return ChirpStackApiPermissionDeniedError(
                f"ChirpStack API permission denied during {operation_name}: {details}"
            )

        if status_code == grpc.StatusCode.NOT_FOUND:
            return ChirpStackNotFoundError(
                f"ChirpStack {operation_name} failed with NOT_FOUND: {details}"
            )

        if status_code == grpc.StatusCode.ALREADY_EXISTS:
            return ChirpStackAlreadyExistsError(
                f"ChirpStack {operation_name} failed with ALREADY_EXISTS: {details}"
            )

        if status_code == grpc.StatusCode.INVALID_ARGUMENT:
            return ChirpStackValidationError(
                f"ChirpStack {operation_name} failed with INVALID_ARGUMENT: {details}"
            )

        if status_code in {
            grpc.StatusCode.DEADLINE_EXCEEDED,
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.CANCELLED,
            grpc.StatusCode.RESOURCE_EXHAUSTED,
            grpc.StatusCode.INTERNAL,
            grpc.StatusCode.UNKNOWN,
            grpc.StatusCode.ABORTED,
        }:
            error_class = (
                ChirpStackApiTimeoutError
                if status_code == grpc.StatusCode.DEADLINE_EXCEEDED
                else ChirpStackApiConnectionError
            )
            return error_class(
                f"ChirpStack {operation_name} failed with {status_code.name}: {details}"
            )

        return ChirpStackApiRequestError(
            f"ChirpStack {operation_name} failed with {status_code.name}: {details}",
            retryable=False,
        )

    def _populate_device_message(
        self,
        *,
        device: Any,
        dev_eui: str,
        name: str,
        application_id: str,
        device_profile_id: str,
        join_eui: str,
        description: str | None,
        is_disabled: bool,
        tags: dict[str, str] | None,
    ) -> None:
        normalized_tags = tags or {}
        device.dev_eui = self._normalize_eui(dev_eui, field_name="dev_eui")
        device.name = self._normalize_required_text(name, field_name="name")
        device.application_id = self._normalize_required_text(
            application_id,
            field_name="chirpstack_application_id",
        )
        device.device_profile_id = self._normalize_required_text(
            device_profile_id,
            field_name="chirpstack_device_profile_id",
        )
        device.join_eui = self._normalize_eui(join_eui, field_name="join_eui")
        device.is_disabled = is_disabled
        if description is not None:
            device.description = description.strip()
        device.tags.clear()
        device.tags.update(normalized_tags)

    def _populate_device_keys_message(
        self,
        *,
        device_keys: Any,
        dev_eui: str,
        app_key: str,
    ) -> None:
        normalized_app_key = self._normalize_app_key(app_key)
        device_keys.dev_eui = self._normalize_eui(dev_eui, field_name="dev_eui")
        # ChirpStack expects the LoRaWAN 1.0.x AppKey in nwk_key.
        device_keys.nwk_key = normalized_app_key

    def _build_device_record(self, device: Any) -> ChirpStackDeviceRecord:
        return ChirpStackDeviceRecord(
            dev_eui=device.dev_eui,
            name=device.name,
            application_id=device.application_id,
            device_profile_id=device.device_profile_id,
            description=device.description or None,
            join_eui=device.join_eui or None,
            is_disabled=device.is_disabled,
            tags=dict(device.tags),
        )

    def _augment_connectivity_hint(self, details: str) -> str:
        normalized = details.lower()
        if "address lookup failed" not in normalized and "name not found" not in normalized:
            return details

        if self.host.strip().lower() != "chirpstack":
            return details

        return (
            f"{details}. Hint: the ChirpStack container/alias 'chirpstack' is not resolvable "
            "from this worker. Verify the ChirpStack stack is running and joined to the "
            "shared Docker network configured by MANEA_CHIRPSTACK_SHARED_NETWORK."
        )

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _validate_configuration(self, operation_label: str) -> None:
        if not self.host:
            raise ChirpStackApiConfigurationError(
                f"CHIRPSTACK_API_HOST is required for {operation_label}"
            )

        if not self.port:
            raise ChirpStackApiConfigurationError(
                f"CHIRPSTACK_API_PORT is required for {operation_label}"
            )

        if not self.token:
            raise ChirpStackApiConfigurationError(
                f"CHIRPSTACK_API_TOKEN is required for {operation_label}"
            )

    def _normalize_required_text(self, value: str | None, *, field_name: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ChirpStackApiConfigurationError(f"{field_name} is required")
        return normalized

    def _normalize_eui(self, value: str | None, *, field_name: str) -> str:
        normalized = "".join((value or "").split()).lower()
        if len(normalized) != 16 or any(char not in "0123456789abcdef" for char in normalized):
            raise ChirpStackApiConfigurationError(
                f"{field_name} must be a valid 16-character hex string"
            )
        return normalized

    def _normalize_app_key(self, value: str | None) -> str:
        normalized = "".join((value or "").split()).lower()
        if len(normalized) != 32 or any(char not in "0123456789abcdef" for char in normalized):
            raise ChirpStackApiConfigurationError(
                "app_key must be a valid 32-character hex string"
            )
        return normalized

    def _load_grpc_dependencies(self) -> tuple[Any, Any, Any]:
        try:
            import grpc
            from chirpstack_api import api
            from google.protobuf.timestamp_pb2 import Timestamp
        except ModuleNotFoundError as exc:
            raise ChirpStackApiConfigurationError(
                "ChirpStack gRPC dependencies are missing. Install requirements and rebuild the Docker image."
            ) from exc

        return grpc, api, Timestamp
