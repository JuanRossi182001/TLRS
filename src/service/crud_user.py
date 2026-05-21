from src.models.user import User, UserSession
from src.schemas.user import (
    TokenData,
    UserCreate,
    UserUpdate
)
from src.settings import settings

from typing import Annotated
import hashlib
import jwt
import secrets
from datetime import datetime, timedelta
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy import delete, or_, select
from src.service.crud_base import CrudBase



oauth_bearer = OAuth2PasswordBearer(tokenUrl='/user/auth/login')
bcryptContext = CryptContext(schemes=['bcrypt'], deprecated ='auto')


class RefreshTokenPair:
    def __init__(self, refresh_token: str, session: UserSession):
        self.refresh_token = refresh_token
        self.session = session


class RefreshSessionResult:
    def __init__(self, token_data: TokenData, refresh_token_pair: RefreshTokenPair):
        self.token_data = token_data
        self.refresh_token_pair = refresh_token_pair


class UserService(CrudBase[User, UserCreate, UserUpdate]):
    model = User

    async def create(self, obj_in: UserCreate) -> User:
        if len(obj_in.password.encode("utf-8")) > 72:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password cannot be longer than 72 bytes.",
            )

        hashed_password = bcryptContext.hash(obj_in.password)
        _user = User(name=obj_in.name,
                     email=obj_in.email,
                     password=hashed_password,
                     id_client=obj_in.id_client,
                     is_admin=obj_in.is_admin)
        self.db.add(_user)
        await self.db.commit()
        await self.db.refresh(_user)
        return _user

    async def auth_user(self, password: str, username: str) -> User: 
        result = await self.db.execute(select(User).filter(
            User.name == username,
            User.deleted == "N",
        ))
        _user = result.scalar_one_or_none()
        if not _user:
            raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
        if not bcryptContext.verify(password, _user.password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Credentials")
        return _user

    async def create_refresh_session(
        self,
        user_id: int,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> RefreshTokenPair:
        await self.enforce_active_session_limit(user_id)

        refresh_token = secrets.token_urlsafe(64)
        token_hash = self.hash_refresh_token(refresh_token)
        session = UserSession(
            user_id=user_id,
            refresh_token_hash=token_hash,
            expires_at=datetime.utcnow()
            + timedelta(days=settings.jwt_refresh_token_expire_days),
            user_agent=self.truncate_user_agent(user_agent),
            ip_address=ip_address,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return RefreshTokenPair(refresh_token=refresh_token, session=session)

    async def enforce_active_session_limit(self, user_id: int) -> None:
        max_active_sessions = settings.user_session_max_active_sessions
        if max_active_sessions < 1:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User session limit must be at least 1.",
            )

        now = datetime.utcnow()
        result = await self.db.execute(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.deleted == "N",
                UserSession.expires_at > now,
            )
            .order_by(UserSession.issued_at.asc(), UserSession.id_session.asc())
            .with_for_update()
        )
        active_sessions = list(result.scalars().all())
        sessions_to_revoke = len(active_sessions) - max_active_sessions + 1
        if sessions_to_revoke <= 0:
            return

        for session in active_sessions[:sessions_to_revoke]:
            session.revoked_at = now

    async def rotate_refresh_session(
        self,
        refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> RefreshSessionResult:
        now = datetime.utcnow()
        token_hash = self.hash_refresh_token(refresh_token)
        result = await self.db.execute(
            select(UserSession, User)
            .join(User, User.id_user == UserSession.user_id)
            .where(
                UserSession.refresh_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.deleted == "N",
                UserSession.expires_at > now,
                User.deleted == "N",
            )
            .with_for_update()
        )
        row = result.one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token.",
            )

        session, user = row
        token_data = TokenData(
            user_id=user.id_user,
            username=user.name,
            client_id=user.id_client,
            is_admin=user.is_admin,
        )
        session.revoked_at = now
        await self.db.flush()
        await self.enforce_active_session_limit(token_data.user_id)

        new_refresh_token = secrets.token_urlsafe(64)
        new_session = UserSession(
            user_id=token_data.user_id,
            refresh_token_hash=self.hash_refresh_token(new_refresh_token),
            expires_at=now + timedelta(days=settings.jwt_refresh_token_expire_days),
            user_agent=self.truncate_user_agent(user_agent),
            ip_address=ip_address,
        )
        self.db.add(new_session)
        await self.db.flush()

        session.replaced_by_session_id = new_session.id_session
        await self.db.commit()
        await self.db.refresh(new_session)

        return RefreshSessionResult(
            token_data=token_data,
            refresh_token_pair=RefreshTokenPair(
                refresh_token=new_refresh_token,
                session=new_session,
            ),
        )

    async def revoke_refresh_session(self, refresh_token: str) -> None:
        now = datetime.utcnow()
        token_hash = self.hash_refresh_token(refresh_token)
        result = await self.db.execute(
            select(UserSession).where(
                UserSession.refresh_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.deleted == "N",
                UserSession.expires_at > now,
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            return

        session.revoked_at = now
        await self.db.commit()

    async def delete_stale_sessions(self, retention_days: int) -> int:
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        result = await self.db.execute(
            delete(UserSession).where(
                UserSession.issued_at < cutoff,
                or_(
                    UserSession.revoked_at.is_not(None),
                    UserSession.expires_at < datetime.utcnow(),
                ),
            )
        )
        await self.db.commit()
        return result.rowcount or 0

    @staticmethod
    def hash_refresh_token(refresh_token: str) -> str:
        return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()

    @staticmethod
    def truncate_user_agent(user_agent: str | None) -> str | None:
        if user_agent is None:
            return None
        return user_agent[:512]

    
    # create acces token
    def create_token(
        self,
        user_id: int,
        username: str,
        client_id: int | None,
        expires_delta: timedelta,
        is_admin: bool,
    ) -> str:
        to_encode = {
            'sub': username,
            'id': user_id,
            'client_id': client_id,
            'is_admin': is_admin,
            'type': 'access',
        }
        expire = datetime.utcnow() + expires_delta
        to_encode.update({'exp': expire})
        if settings.jwt_secret_key is None or settings.jwt_algorithm is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="JWT settings are not configured.",
            )

        encoded_jwt = jwt.encode(
            to_encode,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        return encoded_jwt
    

# get current user
def get_current_user(token: Annotated[str, Depends(oauth_bearer)]) -> TokenData:
    if settings.jwt_secret_key is None or settings.jwt_algorithm is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT settings are not configured.",
        )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        user_id = payload.get('id')
        username = payload.get('sub')

        if user_id is None or username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate user.",
            )

        return TokenData(
            user_id=user_id,
            username=username,
            client_id=payload.get('client_id'),
            is_admin=payload.get('is_admin', False),
        )

    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate user.",
        )
