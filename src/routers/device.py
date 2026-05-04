from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.db.config.connection import get_db
from src.service.device_provisioning_service import DeviceProvisioningService
from src.infrastructure.mqtt.mosquitto_dynamic_security_client import MosquittoDynamicSecurityClient
from src.schemas.device import DeviceCreateSch, DeviceProvisioningResponseSch


router = APIRouter(prefix="/device", tags=["Device"])

