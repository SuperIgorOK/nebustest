from functools import lru_cache
from urllib.parse import quote

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    service_name: str = Field(default="payments-service", alias="SERVICE_NAME")
    api_key: str = Field(default="change-me", alias="API_KEY", min_length=1)
    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT", gt=0)
    postgres_db: str = Field(default="payments", alias="POSTGRES_DB", min_length=1)
    postgres_user: str = Field(default="postgres", alias="POSTGRES_USER", min_length=1)
    postgres_password: str = Field(
        default="postgres",
        alias="POSTGRES_PASSWORD",
        min_length=1,
    )
    database_url: str = Field(
        default="",
        alias="DATABASE_URL",
    )
    rabbitmq_host: str = Field(default="rabbitmq", alias="RABBITMQ_HOST")
    rabbitmq_broker_port: int = Field(default=5672, alias="RABBITMQ_BROKER_PORT", gt=0)
    rabbitmq_default_user: str = Field(
        default="guest",
        alias="RABBITMQ_DEFAULT_USER",
        min_length=1,
    )
    rabbitmq_default_pass: str = Field(
        default="guest",
        alias="RABBITMQ_DEFAULT_PASS",
        min_length=1,
    )
    rabbitmq_url: str = Field(
        default="",
        alias="RABBITMQ_URL",
    )
    payments_queue: str = Field(default="payments.new", alias="PAYMENTS_QUEUE")
    payments_exchange: str = Field(default="payments.events", alias="PAYMENTS_EXCHANGE")
    payments_retry_exchange: str = Field(
        default="payments.retry",
        alias="PAYMENTS_RETRY_EXCHANGE",
    )
    payments_dead_letter_exchange: str = Field(
        default="payments.dlx",
        alias="PAYMENTS_DEAD_LETTER_EXCHANGE",
    )
    payments_dead_letter_queue: str = Field(
        default="payments.dlq",
        alias="PAYMENTS_DEAD_LETTER_QUEUE",
    )
    outbox_poll_interval_seconds: float = Field(
        default=1,
        alias="OUTBOX_POLL_INTERVAL_SECONDS",
        gt=0,
    )
    outbox_batch_size: int = Field(default=100, alias="OUTBOX_BATCH_SIZE", gt=0)
    payment_processing_min_seconds: float = Field(
        default=2,
        alias="PAYMENT_PROCESSING_MIN_SECONDS",
        ge=0,
    )
    payment_processing_max_seconds: float = Field(
        default=5,
        alias="PAYMENT_PROCESSING_MAX_SECONDS",
        ge=0,
    )
    payment_success_rate: float = Field(
        default=0.9,
        alias="PAYMENT_SUCCESS_RATE",
        ge=0,
        le=1,
    )
    message_max_attempts: int = Field(default=3, alias="MESSAGE_MAX_ATTEMPTS", gt=0)
    retry_base_delay_seconds: float = Field(
        default=1,
        alias="RETRY_BASE_DELAY_SECONDS",
        gt=0,
    )
    webhook_timeout_seconds: float = Field(
        default=5,
        alias="WEBHOOK_TIMEOUT_SECONDS",
        gt=0,
    )

    broker_retry_delay_seconds: float = Field(default=5, alias="BROKER_RETRY_DELAY_SECONDS", gt=0)
    webhook_allowed_origins: list[AnyHttpUrl] = Field(
        default_factory=list,
        alias="WEBHOOK_ALLOWED_ORIGINS",
    )

    @field_validator("webhook_allowed_origins")
    @classmethod
    def origins_only(cls, origins: list[AnyHttpUrl]) -> list[AnyHttpUrl]:
        for origin in origins:
            if (
                origin.username
                or origin.password
                or origin.query
                or origin.fragment
                or origin.path not in (None, "/")
            ):
                raise ValueError(
                    "WEBHOOK_ALLOWED_ORIGINS entries must contain only scheme, host and port"
                )
        return origins

    @model_validator(mode="after")
    def validate_processing_window(self) -> "Settings":
        if not self.database_url:
            self.database_url = URL.create(
                "postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
            ).render_as_string(hide_password=False)
        if not self.rabbitmq_url:
            self.rabbitmq_url = (
                f"amqp://{quote(self.rabbitmq_default_user, safe='')}:{quote(self.rabbitmq_default_pass, safe='')}"
                f"@{self.rabbitmq_host}:{self.rabbitmq_broker_port}/"
            )
        if self.payment_processing_min_seconds > self.payment_processing_max_seconds:
            raise ValueError(
                "PAYMENT_PROCESSING_MIN_SECONDS must be less than or equal to "
                "PAYMENT_PROCESSING_MAX_SECONDS"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
