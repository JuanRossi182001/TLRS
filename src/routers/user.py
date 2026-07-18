from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.config.connection import get_db
from src.schemas.user import TokenResponse, UserCreate, UserResponse
from src.service.crud_user import UserService
from src.settings import settings



router = APIRouter(prefix="/user", tags=["Users"])
REFRESH_TOKEN_COOKIE_KEY = "refresh_token"


def refresh_token_cookie_max_age() -> int:
    return settings.jwt_refresh_token_expire_days * 24 * 60 * 60


def refresh_token_cookie_secure() -> bool:
    if settings.refresh_token_cookie_secure is not None:
        return settings.refresh_token_cookie_secure
    return settings.environment.lower() in {"prod", "production"}


def set_refresh_token_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_KEY,
        value=refresh_token,
        max_age=refresh_token_cookie_max_age(),
        httponly=True,
        secure=refresh_token_cookie_secure(),
        samesite=settings.refresh_token_cookie_samesite,
        path=settings.refresh_token_cookie_path,
    )


def delete_refresh_token_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE_KEY,
        httponly=True,
        secure=refresh_token_cookie_secure(),
        samesite=settings.refresh_token_cookie_samesite,
        path=settings.refresh_token_cookie_path,
    )


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
    "/auth/login",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    user = await service.auth_user(
        username=form_data.username,
        password=form_data.password,
    )
    refresh_session = await service.create_refresh_session(
        user_id=user.id_user,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    access_token = service.create_token(
        user_id=user.id_user,
        username=user.name,
        client_id=user.id_client,
        is_admin=user.is_admin,
        session_id=refresh_session.session.id_session,
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )
    set_refresh_token_cookie(response, refresh_session.refresh_token)

    return TokenResponse(
        access_token=access_token,
    )


@router.post(
    "/auth/refresh",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
)
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    refresh_token_cookie = request.cookies.get(REFRESH_TOKEN_COOKIE_KEY)
    if refresh_token_cookie is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cookie is missing.",
        )

    service = UserService(db)
    refresh_result = await service.rotate_refresh_session(
        refresh_token=refresh_token_cookie,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    access_token = service.create_token(
        user_id=refresh_result.token_data.user_id,
        username=refresh_result.token_data.username,
        client_id=refresh_result.token_data.client_id,
        is_admin=refresh_result.token_data.is_admin,
        session_id=refresh_result.session.id_session,
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )
    if refresh_result.refresh_token_pair is not None:
        set_refresh_token_cookie(
            response,
            refresh_result.refresh_token_pair.refresh_token,
        )

    return TokenResponse(
        access_token=access_token,
    )


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    refresh_token_cookie = request.cookies.get(REFRESH_TOKEN_COOKIE_KEY)
    if refresh_token_cookie is None:
        delete_refresh_token_cookie(response)
        return response

    service = UserService(db)
    await service.revoke_refresh_session(refresh_token_cookie)
    delete_refresh_token_cookie(response)
    return response
