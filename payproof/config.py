"""Explicit environment parsing with redacted secrets and no filesystem side effects."""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, model_validator

from payproof.schemas import Contract


class ConfigurationError(ValueError):
    """Sanitized error safe for the CLI; never include environment values."""


class Settings(Contract):
    environment: Literal["development", "test", "production"] = "development"
    port: int = Field(default=8000, ge=1024, le=65535)
    data_dir: Path = Path("data")
    extraction_mode: Literal["disabled", "fixture"] = "disabled"
    secret_key: SecretStr | None = Field(default=None, repr=False, exclude=True)

    @model_validator(mode="after")
    def production_secret(self) -> "Settings":
        if self.environment == "production":
            if self.secret_key is None or len(self.secret_key.get_secret_value().strip()) < 32:
                raise ValueError("production requires a signing secret of at least 32 characters")
        return self


def load_settings(environ: Mapping[str, str]) -> Settings:
    allowed = {
        "PAYPROOF_ENV", "PAYPROOF_PORT", "PAYPROOF_DATA_DIR",
        "PAYPROOF_EXTRACTION_MODE", "PAYPROOF_SECRET_KEY",
    }
    if any(key.startswith("PAYPROOF_") and key not in allowed for key in environ):
        raise ConfigurationError("Unknown PAYPROOF environment variable; consult .env.example")
    raw_port = environ.get("PAYPROOF_PORT", "8000")
    if not raw_port.isascii() or not raw_port.isdecimal():
        raise ConfigurationError("PAYPROOF_PORT must contain ASCII digits")
    raw_secret = environ.get("PAYPROOF_SECRET_KEY", "")
    raw_dir = environ.get("PAYPROOF_DATA_DIR", "./data")
    if not raw_dir.strip():
        raise ConfigurationError("PAYPROOF_DATA_DIR must not be empty")
    try:
        return Settings(
            environment=environ.get("PAYPROOF_ENV", "development"),
            port=int(raw_port),
            data_dir=Path(raw_dir),
            extraction_mode=environ.get("PAYPROOF_EXTRACTION_MODE", "disabled"),
            secret_key=SecretStr(raw_secret) if raw_secret else None,
        )
    except ValidationError:
        raise ConfigurationError(
            "Invalid PayProof settings; check allowed values and the production signing-secret requirement"
        ) from None
