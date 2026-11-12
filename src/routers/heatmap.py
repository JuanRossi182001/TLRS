from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.schemas.heatmap import HeatmapRequest, HeatmapResponse
from src.schemas.user import TokenData
from src.service.heatmap_service import HeatmapService
from src.service.historical_spatial_analytics_service import (
    HistoricalAnalyticsError,
    HistoricalAnalyticsLimitExceeded,
    HistoricalAnalyticsNotFound,
)
from src.service.crud_user import get_current_user
from src.utils.validations import validate_user_service_access


router = APIRouter(prefix="/analytics/heatmaps", tags=["Historical analytics"])


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    response_model=HeatmapResponse,
)
async def query_heatmap(
    request: HeatmapRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    if current_user.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id is required for heatmap analysis.",
        )
    required_service = (
        "asset:get my assets"
        if request.subject_type.value == "asset"
        else "asset-group:get my asset groups"
    )
    await validate_user_service_access(current_user, required_service, db)
    try:
        return await HeatmapService(db).query(client_id=current_user.client_id, request=request)
    except HistoricalAnalyticsNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.") from exc
    except HistoricalAnalyticsLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (HistoricalAnalyticsError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
