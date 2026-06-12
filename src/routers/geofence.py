from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.schemas.geofence import (
    AssetState,
    AssetStatePaginatedResponse,
    GeoFenceActivationUpdate,
    GeoFenceAssignmentCreate,
    GeoFenceAssignmentRead,
    GeoFenceCreate,
    GeoFenceEventPaginatedResponse,
    GeoFenceEventRelevanceFilter,
    GeoFenceEventTimeFilter,
    GeoFenceEventTypeFilter,
    GeoFenceRead,
    GeoFenceUpdate,
)
from src.schemas.user import TokenData
from src.service.crud_geofence import GeoFenceService
from src.service.geofence_evaluation_service import GeoFenceEvaluationService
from src.service.crud_user import get_current_user
from src.utils.validations import validate_user_service_access


router = APIRouter(prefix="/geofences", tags=["Geofences"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=GeoFenceRead,
)
async def create_geofence(
    payload: GeoFenceCreate,
    client_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:create", db)
    resolved_client_id = _resolve_client_id(current_user, client_id)

    service = GeoFenceService(db)
    try:
        return await service.create_geofence(resolved_client_id, payload)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Geofence name already exists for this client.",
        )


@router.get(
    "/my-geofences",
    status_code=status.HTTP_200_OK,
    response_model=list[GeoFenceRead],
)
async def get_my_geofences(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:get my geofences", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceService(db)
    return await service.get_geofences_by_client_id(
        client_id=client_id,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/events/my-events",
    status_code=status.HTTP_200_OK,
    response_model=GeoFenceEventPaginatedResponse,
)
async def get_my_geofence_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    time_filter: GeoFenceEventTimeFilter = Query(default=GeoFenceEventTimeFilter.ALL),
    relevance_filter: GeoFenceEventRelevanceFilter = Query(
        default=GeoFenceEventRelevanceFilter.ALL,
    ),
    event_type: GeoFenceEventTypeFilter | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:get events", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceService(db)
    stats = await service.get_event_stats_by_client_id(
        client_id=client_id,
        time_filter=time_filter,
        relevance_filter=relevance_filter,
        event_type=event_type,
    )
    items = await service.get_events_by_client_id(
        client_id=client_id,
        skip=skip,
        limit=limit,
        time_filter=time_filter,
        relevance_filter=relevance_filter,
        event_type=event_type,
    )

    return {
        "total": stats.total_events,
        "skip": skip,
        "limit": limit,
        "stats": stats,
        "items": items,
    }


@router.get(
    "/{geofence_id}",
    status_code=status.HTTP_200_OK,
    response_model=GeoFenceRead,
)
async def get_geofence(
    geofence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:get", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceService(db)
    geofence = await service.get_geofence_for_client(geofence_id, client_id)
    if geofence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Geofence not found.",
        )

    return geofence


@router.patch(
    "/{geofence_id}",
    status_code=status.HTTP_200_OK,
    response_model=GeoFenceRead,
)
async def update_geofence(
    geofence_id: int,
    payload: GeoFenceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:update", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceService(db)
    try:
        geofence = await service.update_geofence(geofence_id, client_id, payload)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Geofence name already exists for this client.",
        )

    if geofence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Geofence not found.",
        )

    return geofence


@router.patch(
    "/{geofence_id}/activation",
    status_code=status.HTTP_200_OK,
    response_model=GeoFenceRead,
)
async def set_geofence_activation(
    geofence_id: int,
    payload: GeoFenceActivationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:update", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceService(db)
    geofence = await service.set_geofence_active(geofence_id, client_id, payload)
    if geofence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Geofence not found.",
        )

    return geofence


@router.delete(
    "/{geofence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_geofence(
    geofence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:delete", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceService(db)
    deleted = await service.delete_geofence(geofence_id, client_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Geofence not found.",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{geofence_id}/assignments",
    status_code=status.HTTP_201_CREATED,
    response_model=list[GeoFenceAssignmentRead],
)
async def assign_assets_to_geofence(
    geofence_id: int,
    payload: GeoFenceAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:assign asset", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceService(db)
    try:
        result = await service.assign_assets(geofence_id, client_id, payload)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more assets are already assigned to this geofence.",
        )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Geofence not found.",
        )

    assignments, missing_asset_ids = result
    if missing_asset_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "One or more assets were not found for this client.",
                "asset_ids": missing_asset_ids,
            },
        )

    return assignments


@router.get(
    "/{geofence_id}/assignments",
    status_code=status.HTTP_200_OK,
    response_model=list[GeoFenceAssignmentRead],
)
async def get_geofence_assignments(
    geofence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:get assignments", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceService(db)
    assignments = await service.get_assignments(geofence_id, client_id)
    if assignments is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Geofence not found.",
        )

    return assignments


@router.patch(
    "/assignments/{assignment_id}/deactivate",
    status_code=status.HTTP_200_OK,
    response_model=GeoFenceAssignmentRead,
)
async def deactivate_geofence_assignment(
    assignment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:deactivate assignment", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceService(db)
    assignment = await service.deactivate_assignment(assignment_id, client_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found.",
        )

    return assignment


@router.get(
    "/states/my-states",
    status_code=status.HTTP_200_OK,
    response_model=AssetStatePaginatedResponse,
)
async def get_my_asset_states(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:get events", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceEvaluationService(db)
    total, items = await service.get_asset_states(
        client_id=client_id,
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
    "/states/assets/{asset_id}",
    status_code=status.HTTP_200_OK,
    response_model=list[AssetState],
)
async def get_asset_states_by_asset_id(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await validate_user_service_access(current_user, "geofence:get events", db)
    client_id = _resolve_client_id(current_user, None)

    service = GeoFenceEvaluationService(db)
    states = await service.get_asset_states_by_asset_id(
        client_id=client_id,
        asset_id=asset_id,
    )
    if states is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found.",
        )

    return states

def _resolve_client_id(
    current_user: TokenData,
    requested_client_id: int | None,
) -> int:
    if current_user.is_admin and requested_client_id is not None:
        return requested_client_id

    if current_user.client_id is not None:
        return current_user.client_id

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="client_id is required for this geofence operation.",
    )
