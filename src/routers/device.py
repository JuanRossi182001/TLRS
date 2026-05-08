from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.application.security.credential_generator import CredentialGenerator
from src.db.config.connection import get_db
from src.schemas.device import (
    DeviceCreateSch,
    DeviceProvisioningResponseSch,
)
from src.service.device_provisioning_service import DeviceProvisioningService
from src.settings import settings


router = APIRouter(prefix="/devices", tags=["Devices"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DeviceProvisioningResponseSch,
)
def create_device(
    payload: DeviceCreateSch,
    db: Session = Depends(get_db),
):
    service = DeviceProvisioningService(
        db=db,
        credential_generator=CredentialGenerator(),
        mqtt_public_host=settings.mqtt_host,
        mqtt_public_port=settings.mqtt_public_port,
        mqtt_tls_enabled=settings.mqtt_tls_enabled,
    )

    try:
        return service.provision_device(
            serial=payload.serial,
            name=payload.name,
            type=payload.type,
            client_id=payload.client_id,
            asset_id=payload.asset_id,
        )

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device serial or MQTT username already exists.",
        )

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
