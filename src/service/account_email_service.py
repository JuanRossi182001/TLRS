import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User, UserEmailToken, UserSession
from src.service.crud_user import bcryptContext
from src.settings import settings


EMAIL_VERIFICATION = "verify_email"
PASSWORD_RESET = "password_reset"
ACCOUNT_ACTIVATION = "activate_account"
RESEND_COOLDOWN = timedelta(minutes=1)


class AccountEmailService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def create_token(self, user: User, purpose: str) -> str | None:
        now = datetime.utcnow()
        recent_result = await self.db.execute(
            select(UserEmailToken.id_token)
            .where(
                UserEmailToken.user_id == user.id_user,
                UserEmailToken.purpose == purpose,
                UserEmailToken.created_at > now - RESEND_COOLDOWN,
            )
            .limit(1)
        )
        if recent_result.scalar_one_or_none() is not None:
            return None

        await self.db.execute(
            delete(UserEmailToken).where(
                or_(
                    UserEmailToken.used_at.is_not(None),
                    UserEmailToken.expires_at <= now,
                )
            )
        )
        await self.db.execute(
            update(UserEmailToken)
            .where(
                UserEmailToken.user_id == user.id_user,
                UserEmailToken.purpose == purpose,
                UserEmailToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        raw_token = secrets.token_urlsafe(48)
        self.db.add(
            UserEmailToken(
                user_id=user.id_user,
                token_hash=self.hash_token(raw_token),
                purpose=purpose,
                created_at=now,
                expires_at=now
                + timedelta(minutes=settings.email_action_token_expire_minutes),
            )
        )
        await self.db.commit()
        return raw_token

    async def request_verification(self, email: str) -> tuple[str, str] | None:
        user = await self._find_user(email)
        if user is None or user.email_verified_at is not None:
            return None
        if user.email_verification_required:
            return None
        token = await self.create_token(user, EMAIL_VERIFICATION)
        return (user.email, token) if token else None

    async def request_activation(self, email: str) -> tuple[str, str] | None:
        user = await self._find_user(email)
        if (
            user is None
            or not user.email_verification_required
            or user.email_verified_at is not None
        ):
            return None
        token = await self.create_token(user, ACCOUNT_ACTIVATION)
        return (user.email, token) if token else None

    async def request_password_reset(self, email: str) -> tuple[str, str] | None:
        user = await self._find_user(email)
        if user is None:
            return None
        token = await self.create_token(user, PASSWORD_RESET)
        return (user.email, token) if token else None

    async def confirm_email(self, raw_token: str) -> None:
        token, user = await self._get_token(raw_token, EMAIL_VERIFICATION)
        now = datetime.utcnow()
        token.used_at = now
        user.email_verified_at = now
        user.email_verification_required = False
        await self.db.commit()

    async def activate_account(self, raw_token: str, new_password: str) -> None:
        token, user = await self._get_token(raw_token, ACCOUNT_ACTIVATION)
        now = datetime.utcnow()
        token.used_at = now
        user.password = bcryptContext.hash(new_password)
        user.email_verified_at = now
        user.email_verification_required = False
        await self.db.execute(
            update(UserEmailToken)
            .where(
                UserEmailToken.user_id == user.id_user,
                UserEmailToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await self.db.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user.id_user,
                UserSession.deleted == "N",
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self.db.commit()

    async def reset_password(self, raw_token: str, new_password: str) -> None:
        token, user = await self._get_token(raw_token, PASSWORD_RESET)
        now = datetime.utcnow()
        token.used_at = now
        user.password = bcryptContext.hash(new_password)
        user.email_verified_at = user.email_verified_at or now
        user.email_verification_required = False
        await self.db.execute(
            update(UserEmailToken)
            .where(
                UserEmailToken.user_id == user.id_user,
                UserEmailToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await self.db.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user.id_user,
                UserSession.deleted == "N",
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self.db.commit()

    async def _find_user(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User).where(
                func.lower(User.email) == email.lower(),
                User.deleted == "N",
            )
        )
        users = result.scalars().all()
        # Older records may differ only in email casing; never choose one at random.
        return users[0] if len(users) == 1 else None

    async def _get_token(
        self,
        raw_token: str,
        purpose: str,
    ) -> tuple[UserEmailToken, User]:
        result = await self.db.execute(
            select(UserEmailToken, User)
            .join(User, User.id_user == UserEmailToken.user_id)
            .where(
                UserEmailToken.token_hash == self.hash_token(raw_token),
                UserEmailToken.purpose == purpose,
                UserEmailToken.used_at.is_(None),
                UserEmailToken.expires_at > datetime.utcnow(),
                User.deleted == "N",
            )
            .with_for_update()
        )
        row = result.one_or_none()
        if row is None:
            raise ValueError("This link is invalid or has expired.")
        return row
