from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.schemas.user import TokenData  
from src.schemas.device import (
    DeviceCreateSch,
    DeviceProvisioningResponseSch,
    DeviceLastLocation,
    DevicePaginatedResponse,
)
from src.utils.validations import validate_user_service_access
from src.service.crud_user import get_current_user
from src.service.crud_device import DeviceService
from src.service.device_provisioning_service import DeviceProvisioningService


router = APIRouter(prefix="/devices", tags=["Devices"])


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
    response_model=DeviceProvisioningResponseSch,
)
async def create_device(
    payload: DeviceCreateSch,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    await validate_user_service_access(current_user, "device:create device with all credentials", db)
    service = DeviceProvisioningService(db=db)

    try:
        return await service.provision_device(
            serial=payload.serial,
            name=payload.name,
            type=payload.type,
            client_id=payload.client_id,
            asset_id=payload.asset_id,
            communication_protocol=payload.communication_protocol,
            chirpstack_dev_eui=payload.chirpstack_dev_eui,
            chirpstack_application_id=payload.chirpstack_application_id,
            lorawan_class=payload.lorawan_class,
            chirpstack_device_profile_id=payload.chirpstack_device_profile_id,
        )

    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_device_conflict_message(exc),
        )

    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
