from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep
from app.auth import service as auth_service
from app.auth.deps import CurrentUser
from app.auth.schemas import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.auth.security import create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _token_response(user) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.role.value),
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginRequest, session: SessionDep) -> TokenOut:
    user = await auth_service.authenticate(session, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )
    return _token_response(user)


@router.post(
    "/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED
)
async def register(payload: RegisterRequest, session: SessionDep) -> TokenOut:
    user = await auth_service.register_customer(session, payload)
    return _token_response(user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
