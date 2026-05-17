from src.models.user import User
from src.schemas.user import (
    TokenData,
    UserCreate,
    UserUpdate
)
from src.settings import settings

from typing import Annotated
import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy import select
from src.service.crud_base import CrudBase



oauth_bearer = OAuth2PasswordBearer(tokenUrl='/user/login')
bcryptContext = CryptContext(schemes=['bcrypt'], deprecated ='auto')
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
