from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.integrations.chirpstack.api_client import (
    ChirpStackAlreadyExistsError,
    ChirpStackApiConfigurationError,
    ChirpStackApiPermissionDeniedError,
    ChirpStackApiRequestError,
    ChirpStackAuthError,
    ChirpStackNotFoundError,
    ChirpStackUnavailableError,
    ChirpStackValidationError,
)
from src.schemas.user import TokenData  
from src.schemas.device import (
    ChirpStackDeviceCreate,
    DeviceLastLocation,
    DevicePaginatedResponse,
    ChirpStackProvisioningRead,
    ChirpStackRetryProvisioningRequest,
)
from src.utils.validations import validate_user_service_access
from src.service.crud_user import get_current_user
from src.service.crud_device import DeviceService
from src.service.device_provisioning_service import (
    DeviceProvisioningConflictError,
    DeviceProvisioningError,
    DeviceProvisioningNotFoundError,
    DeviceProvisioningService,
)


router = APIRouter(prefix="/devices", tags=["Devices"])


def _require_admin_user(current_user: TokenData) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin users can manage ChirpStack provisioning.",
        )


def _device_conflict_message(exc: IntegrityError) -> str:
    error_text = str(exc.orig) if exc.orig else str(exc)

    constraint_messages = {
        "uq_devices_serial_active": "Device serial already exists.",
        "uq_devices_asset_id_active": "Asset already has an active device assigned.",
        "uq_devices_chirpstack_dev_eui_active": "ChirpStack DevEUI already exists.",
    }

    for constraint_name, message in constraint_messages.items():
        if constraint_name in error_text:
            return message

    return "Device serial, asset or ChirpStack DevEUI already exists."


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ChirpStackProvisioningRead,
)
async def create_device(
    payload: ChirpStackDeviceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    _require_admin_user(current_user)
    service = DeviceProvisioningService(db=db)

    try:
        return await service.provision_device(
            serial=payload.serial,
            name=payload.name,
            type=payload.type,
            dev_eui=payload.dev_eui,
            join_eui=payload.join_eui,
            app_key=payload.app_key,
            client_id=payload.client_id,
            asset_id=payload.asset_id,
            communication_protocol=payload.communication_protocol,
            chirpstack_application_id=payload.chirpstack_application_id,
            chirpstack_device_profile_id=payload.chirpstack_device_profile_id,
            description=payload.description,
            is_disabled=payload.is_disabled,
        )

    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_device_conflict_message(exc),
        )

    except DeviceProvisioningConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    except DeviceProvisioningError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    except ChirpStackUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )

    except (
        ChirpStackAuthError,
        ChirpStackApiConfigurationError,
        ChirpStackApiPermissionDeniedError,
        ChirpStackValidationError,
        ChirpStackApiRequestError,
        ChirpStackNotFoundError,
        ChirpStackAlreadyExistsError,
    ) as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )


@router.post(
    "/{id_device}/retry-provisioning",
    status_code=status.HTTP_200_OK,
    response_model=ChirpStackProvisioningRead,
)
async def retry_provisioning(
    id_device: int,
    payload: ChirpStackRetryProvisioningRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    _require_admin_user(current_user)
    service = DeviceProvisioningService(db=db)

    try:
        return await service.retry_provisioning(
            device_id=id_device,
            app_key=payload.app_key,
        )
    except DeviceProvisioningNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except DeviceProvisioningConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except DeviceProvisioningError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except ChirpStackUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except (
        ChirpStackAuthError,
        ChirpStackApiConfigurationError,
        ChirpStackApiPermissionDeniedError,
        ChirpStackValidationError,
        ChirpStackApiRequestError,
        ChirpStackNotFoundError,
        ChirpStackAlreadyExistsError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )


@router.get(
    "/{id_device}/provisioning",
    status_code=status.HTTP_200_OK,
    response_model=ChirpStackProvisioningRead,
)
async def get_device_provisioning(
    id_device: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    _require_admin_user(current_user)
    service = DeviceProvisioningService(db=db)

    try:
        return await service.get_provisioning(id_device)
    except DeviceProvisioningNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.get(
    "/my-devices",
    status_code=status.HTTP_200_OK,
    response_model=DevicePaginatedResponse,
)
async def get_my_devices(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):

    await validate_user_service_access(current_user, "device:get my devices", db)
    device_service = DeviceService(db)

    stats = await device_service.get_device_stats_by_client_id(
        client_id=current_user.client_id,
    )
    items = await device_service.get_devices_by_client_id(
        client_id=current_user.client_id,
        skip=skip,
        limit=limit,
    )

    return {
        "total": stats.total_devices,
        "skip": skip,
        "limit": limit,
        "stats": stats,
        "items": items,
    }


@router.get(
    "/my-devices/latest-locations",
    status_code=status.HTTP_200_OK,
    response_model=list[DeviceLastLocation],
)
async def get_my_devices_latest_locations(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(
        current_user,
        "device:get latest locations",
        db,
    )
    device_service = DeviceService(db)

    return await device_service.get_latest_locations_by_client_id(
        client_id=current_user.client_id,
    )
