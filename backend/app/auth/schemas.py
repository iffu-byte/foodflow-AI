from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str | None
    phone: str | None
    role: Role
    is_active: bool


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginRequest(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=160)
    password: str = Field(min_length=4, max_length=120)


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=160)
    password: str = Field(min_length=6, max_length=120)
    phone: str | None = Field(default=None, max_length=24)
    home_lat: float | None = Field(default=None, ge=-90, le=90)
    home_lng: float | None = Field(default=None, ge=-180, le=180)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
