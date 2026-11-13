from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_access_token
from app.db import get_session
from app.domain.models import Role, User

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        user_id = None
    user = await session.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="account is not active",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    async def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient permissions for this action",
            )
        return user

    return dependency


CustomerUser = Annotated[User, Depends(require_roles(Role.CUSTOMER))]
OrderViewUser = Annotated[
    User,
    Depends(require_roles(Role.CUSTOMER, Role.RIDER, Role.RESTAURANT, Role.ADMIN)),
]
RiderUser = Annotated[User, Depends(require_roles(Role.RIDER))]
RestaurantUser = Annotated[User, Depends(require_roles(Role.RESTAURANT))]
AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
StaffUser = Annotated[User, Depends(require_roles(Role.ADMIN, Role.RESTAURANT))]
DispatchUser = Annotated[User, Depends(require_roles(Role.ADMIN, Role.RIDER))]
