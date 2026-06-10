from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.security.credential_generator import CredentialGenerator
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
from src.infrastructure.mqtt.emqx_cloud_provisioning_client import EMQXCloudProvisioningClient
from src.settings import settings


router = APIRouter(prefix="/devices", tags=["Devices"])


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

    emqx_client = EMQXCloudProvisioningClient(
        api_base_url=settings.emqx_api_base_url,
        api_key=settings.emqx_api_key,
        api_secret=settings.emqx_api_secret,
        authentication_id=settings.emqx_authentication_id,
        authorization_enabled=settings.emqx_authorization_enabled,
    )

    service = DeviceProvisioningService(
        db=db,
        credential_generator=CredentialGenerator(),
        mqtt_broker_client=emqx_client,
        mqtt_public_host=settings.mqtt_host,
        mqtt_public_port=settings.mqtt_port,
        mqtt_tls_enabled=settings.mqtt_tls_enabled,
    )

    try:
        return await service.provision_device(
            serial=payload.serial,
            name=payload.name,
            type=payload.type,
            client_id=payload.client_id,
            asset_id=payload.asset_id,
        )

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device serial or MQTT username already exists.",
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

    total = await device_service.count_devices_by_client_id(client_id=current_user.client_id)
    items = await device_service.get_devices_by_client_id(
        client_id=current_user.client_id,
        skip=skip,
        limit=limit,
    )

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
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
