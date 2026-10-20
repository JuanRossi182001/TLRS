from typing import Annotated
import hashlib
import jwt
import secrets
from datetime import datetime, timedelta
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy import delete, or_, select, func, update

from src.models.user import User, UserSession
from src.models.client import Client
from src.schemas.user import (
    TokenData,
    UserCreate,
    UserUpdate,
    UserResponse,
    UserDashboardResponse
)
from src.settings import settings
from src.service.crud_base import CrudBase



oauth_bearer = OAuth2PasswordBearer(tokenUrl='/user/auth/login')
bcryptContext = CryptContext(schemes=['bcrypt'], deprecated ='auto')


class RefreshTokenPair:
    def __init__(self, refresh_token: str, session: UserSession):
        self.refresh_token = refresh_token
        self.session = session


class RefreshSessionResult:
    def __init__(
        self,
        token_data: TokenData,
        session: UserSession,
        refresh_token_pair: RefreshTokenPair | None = None,
    ):
        self.token_data = token_data
        self.session = session
        self.refresh_token_pair = refresh_token_pair


class UserService(CrudBase[User, UserCreate, UserUpdate]):
    model = User

    async def get_active_user_by_id(self, user_id: int) -> User | None:
        result = await self.db.execute(
            select(User).where(
                User.id_user == user_id,
                User.deleted == "N",
            )
        )
        return result.scalar_one_or_none()

    async def get_active_session(
        self,
        *,
        user_id: int,
        session_id: int,
    ) -> UserSession | None:
        now = datetime.utcnow()
        result = await self.db.execute(
            select(UserSession).where(
                UserSession.id_session == session_id,
                UserSession.user_id == user_id,
                UserSession.deleted == "N",
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

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
            reused_result = await self._reuse_recently_rotated_session(
                refresh_token=refresh_token,
                now=now,
                user_agent=user_agent,
                ip_address=ip_address,
            )
            if reused_result is not None:
                return reused_result

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
            session=new_session,
            refresh_token_pair=RefreshTokenPair(
                refresh_token=new_refresh_token,
                session=new_session,
            ),
        )

    async def _reuse_recently_rotated_session(
        self,
        *,
        refresh_token: str,
        now: datetime,
        user_agent: str | None,
        ip_address: str | None,
    ) -> RefreshSessionResult | None:
        grace_seconds = settings.refresh_token_reuse_grace_seconds
        if grace_seconds < 1:
            return None

        token_hash = self.hash_refresh_token(refresh_token)
        cutoff = now - timedelta(seconds=grace_seconds)
        result = await self.db.execute(
            select(UserSession, User)
            .join(User, User.id_user == UserSession.user_id)
            .where(
                UserSession.refresh_token_hash == token_hash,
                UserSession.deleted == "N",
                UserSession.revoked_at.is_not(None),
                UserSession.revoked_at >= cutoff,
                UserSession.replaced_by_session_id.is_not(None),
                User.deleted == "N",
            )
        )
        row = result.one_or_none()
        if row is None:
            return None

        previous_session, user = row
        if not self._request_fingerprint_matches(
            session=previous_session,
            user_agent=user_agent,
            ip_address=ip_address,
        ):
            return None

        replacement_result = await self.db.execute(
            select(UserSession).where(
                UserSession.id_session == previous_session.replaced_by_session_id,
                UserSession.user_id == previous_session.user_id,
                UserSession.deleted == "N",
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
        )
        replacement_session = replacement_result.scalar_one_or_none()
        if replacement_session is None:
            return None

        return RefreshSessionResult(
            token_data=TokenData(
                user_id=user.id_user,
                username=user.name,
                client_id=user.id_client,
                is_admin=user.is_admin,
            ),
            session=replacement_session,
        )

    def _request_fingerprint_matches(
        self,
        *,
        session: UserSession,
        user_agent: str | None,
        ip_address: str | None,
    ) -> bool:
        normalized_user_agent = self.truncate_user_agent(user_agent)
        if (
            session.user_agent
            and normalized_user_agent
            and session.user_agent != normalized_user_agent
        ):
            return False

        if session.ip_address and ip_address and session.ip_address != ip_address:
            return False

        return True

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
        now = datetime.utcnow()
        cutoff = now - timedelta(days=retention_days)
        stale_session_ids = select(UserSession.id_session).where(
            UserSession.issued_at < cutoff,
            or_(
                UserSession.revoked_at.is_not(None),
                UserSession.expires_at < now,
            ),
        )

        await self.db.execute(
            update(UserSession)
            .where(UserSession.replaced_by_session_id.in_(stale_session_ids))
            .values(replaced_by_session_id=None)
            .execution_options(synchronize_session=False)
        )
        result = await self.db.execute(
            delete(UserSession)
            .where(
                UserSession.id_session.in_(stale_session_ids),
            )
            .execution_options(synchronize_session=False)
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
        session_id: int,
    ) -> str:
        to_encode = {
            'sub': username,
            'id': user_id,
            'client_id': client_id,
            'is_admin': is_admin,
            'session_id': session_id,
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
    
    async def get_active_users_count(self) -> int:
        return await self.db.scalar(select(func.count(User.id_user)).where(User.deleted == "N"))

    async def get_users_by_client_id(
        self,
        client_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[UserResponse]:
        stmt = (
            select(
                User.id_user,
                User.name,
                User.email,
                User.id_client,
                User.is_admin,
            )
            .where(
                User.id_client == client_id,
                User.deleted == "N",
            )
            .limit(limit)
            .offset(skip)
        )
        result = await self.db.execute(stmt)
        return result.mappings().all()

    async def deactivate_user(self, user_id: int) -> User | None:
        user = await self.get(user_id)
        if user is None:
            return None

        user.deleted = "Y"

        await self.db.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.deleted == "N",
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.utcnow())
            .execution_options(synchronize_session=False)
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def reactivate_user(self, user_id: int) -> User | None:
        user = await self.get(user_id, include_deleted=True)
        if user is None:
            return None

        user.deleted = "N"
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def get_users_dashboard(self, skip: int = 0, limit: int = 20) -> list[UserDashboardResponse]:
        latest_sessions = (
            select(
                UserSession.user_id,
                func.max(UserSession.issued_at).label("last_login"),
            )
            .where(
                UserSession.deleted == "N",
                UserSession.revoked_at.is_(None),
            )
            .group_by(UserSession.user_id)
            .subquery()
        )
        stmt = (
            select(
                User.id_user,
                Client.name.label("client_name"),
                User.is_admin,
                latest_sessions.c.last_login,
            )
            .where(User.deleted == "N")
            .outerjoin(Client, User.id_client == Client.id_client)
            .outerjoin(latest_sessions, User.id_user == latest_sessions.c.user_id)
            .limit(limit)
            .offset(skip)
        )
        result = await self.db.execute(stmt)
        return result.mappings().all()

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

        if payload.get('type') != 'access':
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate user.",
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
            session_id=payload.get('session_id'),
        )

    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate user.",
        )
