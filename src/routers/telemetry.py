from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.application.telemetry.ingress.http_telemetry_ingress import HttpTelemetryIngress
from src.application.telemetry.auth.hmac_device_authenticator import HmacDeviceAuthenticator
from src.application.telemetry.parser.json_telemetry_parser import JsonTelemetryParser
from src.db.config.connection import get_db
from src.service.telemetry_ingestion_service import TelemetryIngestionService

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])


@router.post(
    "/ingest",
    status_code=status.HTTP_200_OK,
    summary="Receives telemetry from devices",
)
async def ingest_telemetry(
    request: Request,
    db: Session = Depends(get_db),
):
    raw_payload = (await request.body()).decode("utf-8")
    headers = {k.lower(): v for k, v in request.headers.items()}
    source_ip = request.client.host if request.client else None

    ingress = HttpTelemetryIngress()
    envelope = ingress.build_envelope(
        raw_payload=raw_payload,
        headers=headers,
        source_ip=source_ip,
    )

    authenticator = HmacDeviceAuthenticator(db=db)
    parser = JsonTelemetryParser()

    ingestion_service = TelemetryIngestionService(
        db=db,
        authenticator=authenticator,
        parser=parser,
    )

    result = ingestion_service.ingest(envelope)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.failure_reason,
        )

    return {
        "message": "Telemetry processed successfully",
        "device_id": result.device.id_device if result.device else None,
        "location_id": result.location.id_location if result.location else None,
    }