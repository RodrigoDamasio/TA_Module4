"""Application settings, read once from environment variables."""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    """Every setting the backend needs. See the README for the variable names."""

    database_url: str
    db_pool_size: int
    jwt_secret: str
    jwt_algorithm: str
    jwt_ttl_minutes: int
    payment_api_url: str
    payment_api_key: str
    smtp_host: str
    smtp_port: int
    mail_from: str


@lru_cache
def get_settings() -> Settings:
    """Build the settings from the environment (cached for the process lifetime)."""
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./shopflow.db"),
        db_pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        jwt_secret=os.environ["JWT_SECRET"],
        jwt_algorithm="HS256",
        jwt_ttl_minutes=int(os.getenv("JWT_TTL_MINUTES", "60")),
        payment_api_url=os.getenv("PAYMENT_API_URL", "https://payments.example.com"),
        payment_api_key=os.getenv("PAYMENT_API_KEY", ""),
        smtp_host=os.getenv("SMTP_HOST", "localhost"),
        smtp_port=int(os.getenv("SMTP_PORT", "25")),
        mail_from=os.getenv("MAIL_FROM", "orders@shopflow.example"),
    )
