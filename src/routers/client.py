from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.schemas.client import ClientCreate, ClientResponse, ClientUpdate
from src.schemas.user import TokenData
from src.service.crud_client import ClientEmailConflictError, ClientService
from src.service.crud_user import get_current_user


router = APIRouter(prefix="/admin/clients", tags=["Admin Clients"])


def _require_admin(current_user: TokenData) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin users can manage clients.",
        )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ClientResponse,
)
async def create_client(
    payload: ClientCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    _require_admin(current_user)
    service = ClientService(db)
    try:
        return await service.create_client(payload)
    except ClientEmailConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/{client_id}",
    status_code=status.HTTP_200_OK,
    response_model=ClientResponse,
)
async def get_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    _require_admin(current_user)
    client = await ClientService(db).get_client(client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found.",
        )
    return client


@router.patch(
    "/{client_id}",
    status_code=status.HTTP_200_OK,
    response_model=ClientResponse,
)
async def update_client(
    client_id: int,
    payload: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    _require_admin(current_user)
    service = ClientService(db)
    try:
        client = await service.update_client(client_id, payload)
    except ClientEmailConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found.",
        )
    return client


@router.delete(
    "/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
) -> Response:
    _require_admin(current_user)
    client = await ClientService(db).delete_client(client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
