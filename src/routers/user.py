from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.schemas.user import TokenResponse, UserCreate, UserResponse
from src.service.crud_user import UserService



router = APIRouter(prefix="/user", tags=["Users"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)

    try:
        return await service.create(payload)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists.",
        )


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    user = await service.auth_user(
        username=form_data.username,
        password=form_data.password,
    )
    access_token = service.create_token(
        user_id=user.id_user,
        username=user.name,
        client_id=user.id_client,
        is_admin=user.is_admin,
        expires_delta=timedelta(minutes=60),
    )

    return TokenResponse(access_token=access_token)
