from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import RegisterRequest
from app.auth.security import hash_password, verify_password
from app.domain.exceptions import BadRequestError, ConflictError
from app.domain.models import Customer, Role, User


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    normalized = email.strip().lower()
    user = (
        await session.execute(select(User).where(func.lower(User.email) == normalized))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def register_customer(session: AsyncSession, payload: RegisterRequest) -> User:
    normalized = payload.email.strip().lower()
    existing = (
        await session.execute(select(User).where(func.lower(User.email) == normalized))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("an account with this email already exists")

    user = User(
        name=payload.name.strip(),
        role=Role.CUSTOMER,
        email=normalized,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(
        Customer(
            user_id=user.id,
            home_lat=payload.home_lat if payload.home_lat is not None else 17.4401,
            home_lng=payload.home_lng if payload.home_lng is not None else 78.3489,
            budget_pref="medium",
            diet_pref=None,
        )
    )
    await session.commit()
    await session.refresh(user)
    return user


async def get_user(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.get(User, user_id)


def validate_role(user: User, *roles: Role) -> None:
    if user.role not in roles:
        raise BadRequestError("you are not allowed to perform this action")
