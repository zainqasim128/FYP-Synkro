"""
Application configuration using Pydantic Settings.
Loads configuration from environment variables.
"""
from typing import List, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
import json


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    APP_NAME: str = "Synkro"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"

    # Security
    SECRET_KEY: str = "dev-secret-key-change-in-production-at-least-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://synkro:synkro123@localhost:5432/synkro"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # OpenAI
    OPENAI_API_KEY: str = ""

    # Groq (FREE alternative - get key at https://console.groq.com/keys)
    GROQ_API_KEY: str = ""

    # AWS S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_BUCKET_NAME: str = ""
    AWS_REGION: str = "us-east-1"

    # Cloudinary (alternative to S3)
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # CORS
    ALLOWED_ORIGINS: Union[str, List[str]] = '["http://localhost:3000"]'

    # Gmail IMAP (simple App Password method)
    GMAIL_EMAIL: str = ""
    GMAIL_APP_PASSWORD: str = ""

    # Google OAuth (optional alternative)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""

    # Slack OAuth
    SLACK_CLIENT_ID: str = ""
    SLACK_CLIENT_SECRET: str = ""
    SLACK_REDIRECT_URI: str = ""
    # Signing secret for Events API; used to verify incoming webhook signatures
    SLACK_SIGNING_SECRET: str = ""

    # Frontend URL (used for OAuth callback redirects)
    FRONTEND_URL: str = "http://localhost:3000"

    # Demo: auto-provision Slack for every new registered user
    DEMO_SLACK_TOKEN: str = ""
    DEMO_SLACK_TEAM_ID: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow"
    )

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v):
        """Parse ALLOWED_ORIGINS from JSON string or list"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [v]
        return v

    @property
    def database_url_async(self) -> str:
        """Get async database URL"""
        return self.DATABASE_URL

    @property
    def database_url_sync(self) -> str:
        """Get sync database URL for Alembic"""
        return self.DATABASE_URL.replace("+asyncpg", "").replace("+aiosqlite", "")

    @property
    def use_s3(self) -> bool:
        """Check if S3 is configured with real credentials (not placeholders)"""
        placeholders = {'', 'your-aws-access-key', 'your-aws-secret-key', 'your-key', 'placeholder'}
        return bool(
            self.AWS_ACCESS_KEY_ID and
            self.AWS_SECRET_ACCESS_KEY and
            self.AWS_ACCESS_KEY_ID.lower() not in placeholders and
            self.AWS_SECRET_ACCESS_KEY.lower() not in placeholders and
            not self.AWS_ACCESS_KEY_ID.lower().startswith('your-')
        )

    @property
    def use_cloudinary(self) -> bool:
        """Check if Cloudinary is configured"""
        return bool(self.CLOUDINARY_CLOUD_NAME and self.CLOUDINARY_API_KEY)


# Global settings instance
settings = Settings()
