from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import quote

from src.db.config.connection import get_db
from src.schemas.user import (
    AccountActionResponse,
    AdminUserInviteCreate,
    AdminUserInviteResponse,
    EmailActionRequest,
    EmailTokenRequest,
    PasswordResetRequest,
    TokenData,
    TokenResponse,
    UserResponse,
)
from src.service.account_email_service import (
    ACCOUNT_ACTIVATION,
    AccountEmailService,
)
from src.service.crud_user import UserService, get_current_user
from src.service.email_service import send_email_action_link
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
    response_model=AdminUserInviteResponse,
)
async def create_user(
    payload: AdminUserInviteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can create users.",
        )

    service = UserService(db)

    try:
        user = await service.create_invited_user(payload)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists.",
        )

    try:
        token = await AccountEmailService(db).create_token(
            user,
            ACCOUNT_ACTIVATION,
        )
        email_sent = False
        if token:
            link = (
                f"{settings.app_public_url.rstrip('/')}/activate-account"
                f"#token={quote(token)}"
            )
            email_sent = await send_email_action_link(
                recipient=user.email,
                action="activate",
                link=link,
            )
        return {
            "id_user": user.id_user,
            "name": user.name,
            "email": user.email,
            "id_client": user.id_client,
            "is_admin": user.is_admin,
            "invitation_email_sent": email_sent,
        }

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The account was created, but its verification email could not be prepared.",
        )


@router.post(
    "/auth/account-activation/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AccountActionResponse,
)
async def request_account_activation(
    payload: EmailActionRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await AccountEmailService(db).request_activation(payload.email)
    if result:
        recipient, token = result
        link = (
            f"{settings.app_public_url.rstrip('/')}/activate-account"
            f"#token={quote(token)}"
        )
        await send_email_action_link(
            recipient=recipient,
            action="activate",
            link=link,
        )
    return {"message": "Si la cuenta pendiente existe, enviaremos instrucciones al correo."}


@router.post(
    "/auth/account-activation/confirm",
    status_code=status.HTTP_200_OK,
    response_model=AccountActionResponse,
)
async def confirm_account_activation(
    payload: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        await AccountEmailService(db).activate_account(
            payload.token,
            payload.new_password,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return {"message": "Cuenta activada. Ya puedes iniciar sesión."}


@router.post(
    "/auth/email-verification/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AccountActionResponse,
)
async def request_email_verification(
    payload: EmailActionRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await AccountEmailService(db).request_verification(payload.email)
    if result:
        recipient, token = result
        link = (
            f"{settings.app_public_url.rstrip('/')}/verify-email"
            f"#token={quote(token)}"
        )
        await send_email_action_link(
            recipient=recipient,
            action="verify",
            link=link,
        )
    return {"message": "Si la cuenta existe, enviaremos instrucciones al correo."}


@router.post(
    "/auth/email-verification/confirm",
    status_code=status.HTTP_200_OK,
    response_model=AccountActionResponse,
)
async def confirm_email_verification(
    payload: EmailTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        await AccountEmailService(db).confirm_email(payload.token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return {"message": "Correo verificado correctamente."}


@router.post(
    "/auth/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AccountActionResponse,
)
async def request_password_reset(
    payload: EmailActionRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await AccountEmailService(db).request_password_reset(payload.email)
    if result:
        recipient, token = result
        link = (
            f"{settings.app_public_url.rstrip('/')}/reset-password"
            f"#token={quote(token)}"
        )
        await send_email_action_link(
            recipient=recipient,
            action="reset",
            link=link,
        )
    return {
        "message": "Si la cuenta existe, enviaremos instrucciones al correo."
    }


@router.post(
    "/auth/password-reset/confirm",
    status_code=status.HTTP_200_OK,
    response_model=AccountActionResponse,
)
async def confirm_password_reset(
    payload: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        await AccountEmailService(db).reset_password(
            payload.token,
            payload.new_password,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return {"message": "Contraseña actualizada. Inicia sesión nuevamente."}


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
