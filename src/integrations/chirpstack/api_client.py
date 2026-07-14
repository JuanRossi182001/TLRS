from __future__ import annotations

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


class ChirpStackApiAuthenticationError(ChirpStackApiError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ChirpStackApiPermissionDeniedError(ChirpStackApiError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class ChirpStackApiTimeoutError(ChirpStackApiError):
    def __init__(self, message: str):
        super().__init__(message, retryable=True)


class ChirpStackApiConnectionError(ChirpStackApiError):
    def __init__(self, message: str):
        super().__init__(message, retryable=True)


class ChirpStackApiRequestError(ChirpStackApiError):
    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message, retryable=retryable)


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
        grpc, api, timestamp_class = self._load_grpc_dependencies()

        if not self.host:
            raise ChirpStackApiConfigurationError(
                "CHIRPSTACK_API_HOST is required for gRPC downlinks"
            )

        if not self.port:
            raise ChirpStackApiConfigurationError(
                "CHIRPSTACK_API_PORT is required for gRPC downlinks"
            )

        if not self.token:
            raise ChirpStackApiConfigurationError(
                "CHIRPSTACK_API_TOKEN is required for gRPC downlinks"
            )

        if not dev_eui.strip():
            raise ChirpStackApiConfigurationError("ChirpStack dev_eui is required")

        if f_port <= 0:
            raise ChirpStackApiConfigurationError("ChirpStack f_port must be greater than 0")

        if not data:
            raise ChirpStackApiConfigurationError("ChirpStack downlink data must not be empty")

        channel = self._build_channel()
        try:
            client = api.DeviceServiceStub(channel)
            request = api.EnqueueDeviceQueueItemRequest()
            request.queue_item.dev_eui = "".join(dev_eui.split()).lower()
            request.queue_item.confirmed = confirmed
            request.queue_item.f_port = f_port
            request.queue_item.data = data

            if expires_at is not None:
                expires_at_proto = timestamp_class()
                expires_at_proto.FromDatetime(self._normalize_datetime(expires_at))
                request.queue_item.expires_at.CopyFrom(expires_at_proto)

            response = client.Enqueue(
                request,
                metadata=self._metadata(),
                timeout=self.timeout_seconds,
            )
        except grpc.FutureTimeoutError as exc:
            raise ChirpStackApiTimeoutError(
                f"ChirpStack enqueue timed out after {self.timeout_seconds} seconds"
            ) from exc
        except grpc.RpcError as exc:
            raise self._map_rpc_error(exc) from exc
        except Exception as exc:
            raise ChirpStackApiConnectionError(
                f"ChirpStack enqueue failed: {exc}"
            ) from exc
        finally:
            channel.close()

        if not response.id:
            raise ChirpStackApiRequestError(
                "ChirpStack enqueue succeeded without returning a queue item id",
                retryable=False,
            )

        return response.id

    def _build_channel(self) -> Any:
        grpc, _, _ = self._load_grpc_dependencies()
        target = f"{self.host}:{self.port}"
        if self.use_tls:
            return grpc.secure_channel(target, grpc.ssl_channel_credentials())
        return grpc.insecure_channel(target)

    def _metadata(self) -> list[tuple[str, str]]:
        return [("authorization", f"Bearer {self.token}")]

    def _map_rpc_error(self, exc: Any) -> ChirpStackApiError:
        grpc, _, _ = self._load_grpc_dependencies()
        status_code = exc.code()
        details = (exc.details() or "Unknown gRPC error").strip()
        details = self._augment_connectivity_hint(details)

        if status_code == grpc.StatusCode.UNAUTHENTICATED:
            return ChirpStackApiAuthenticationError(
                f"ChirpStack API authentication failed: {details}"
            )

        if status_code == grpc.StatusCode.PERMISSION_DENIED:
            return ChirpStackApiPermissionDeniedError(
                f"ChirpStack API permission denied: {details}"
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
                f"ChirpStack enqueue failed with {status_code.name}: {details}"
            )

        return ChirpStackApiRequestError(
            f"ChirpStack enqueue failed with {status_code.name}: {details}",
            retryable=False,
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
