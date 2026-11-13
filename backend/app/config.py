from functools import lru_cache
from secrets import token_urlsafe

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "FoodFlow AI"
    env: str = "dev"
    database_url: str = "postgresql+asyncpg://foodflow:foodflow@localhost:5432/foodflow"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173"
    routing_provider: str = "haversine"
    osrm_base_url: str = "http://localhost:5000"
    routing_timeout_s: float = 2.0
    routing_cache_ttl_s: float = 300.0
    offer_sweep_interval_s: float = 5.0
    payment_provider: Literal["demo", "razorpay"] = "demo"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    payment_timeout_s: float = 8.0
    eta_model_path: str = "artifacts/eta_model.joblib"
    auth_secret: str = ""
    auth_token_ttl_min: int = 1440
    demo_password: str = "demo1234"

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        """Require a supplied signing key outside explicitly local environments.

        A process-local key keeps the zero-config developer experience intact while
        preventing a source-controlled fallback from signing deployable tokens.
        """
        if not self.auth_secret and self.env.lower() in {"dev", "test"}:
            self.auth_secret = token_urlsafe(48)
        elif not self.auth_secret:
            raise ValueError("AUTH_SECRET must be set when ENV is not dev or test")
        if self.payment_provider == "razorpay" and (
            not self.razorpay_key_id or not self.razorpay_key_secret
        ):
            raise ValueError(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required when "
                "PAYMENT_PROVIDER=razorpay"
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
