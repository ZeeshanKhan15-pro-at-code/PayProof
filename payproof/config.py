"""Explicit environment parsing with redacted secrets and no filesystem side effects."""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, model_validator

from payproof.schemas import Contract


class ConfigurationError(ValueError):
    """Sanitized error safe for the CLI; never include environment values."""


class Settings(Contract):
    environment: Literal["development", "test", "production"] = "development"
    port: int = Field(default=8000, ge=1024, le=65535)
    data_dir: Path = Path("data")
    extraction_mode: Literal["disabled", "fixture", "live"] = "disabled"
    secret_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    operator_token: SecretStr | None = Field(default=None, repr=False, exclude=True)
    provider_api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)
    public_live_enabled: bool = False
    public_live_max_calls: int = Field(default=20, ge=1, le=100)
    provider: Literal["openai", "featherless"] = "openai"
    provider_base_url: str | None = None
    provider_model: str | None = Field(default=None, min_length=1, max_length=256)
    extraction_timeout_seconds: int = Field(default=30, ge=1, le=60)

    @model_validator(mode="after")
    def production_secret(self) -> "Settings":
        if self.provider_base_url is not None:
            url = urlsplit(self.provider_base_url)
            host = "api.featherless.ai" if self.provider == "featherless" else "api.openai.com"
            if (
                url.scheme != "https"
                or url.netloc != host
                or url.path.rstrip("/") != "/v1"
                or url.query
                or url.fragment
            ):
                raise ValueError("provider URL must be the selected provider HTTPS API root")
        if self.provider_model is not None and any(
            secret is not None
            and secret.get_secret_value()
            and secret.get_secret_value() in self.provider_model
            for secret in (self.provider_api_key, self.secret_key, self.operator_token)
        ):
            raise ValueError("provider model must not contain a configured credential")
        if (
            self.secret_key is not None
            and self.provider_api_key is not None
            and self.secret_key.get_secret_value() == self.provider_api_key.get_secret_value()
        ):
            raise ValueError("session signing secret must differ from provider credential")
        if self.public_live_enabled and self.extraction_mode != "live":
            raise ValueError("public live extraction requires live mode")
        if self.extraction_mode == "live":
            if (
                self.provider_api_key is None
                or not self.provider_api_key.get_secret_value().strip()
                or self.provider_model is None
                or not self.provider_model.strip()
            ):
                raise ValueError("live extraction requires provider key and model")
        if self.operator_token is not None:
            if any(
                secret is not None
                and secret.get_secret_value() == self.operator_token.get_secret_value()
                for secret in (self.secret_key, self.provider_api_key)
            ):
                raise ValueError("operator token must be distinct from other secrets")
            if (
                len(self.operator_token.get_secret_value().strip()) < 32
                or self.secret_key is None
                or len(self.secret_key.get_secret_value().strip()) < 32
            ):
                raise ValueError("web operator gate requires a long token and signing secret")
        if self.environment == "production":
            if self.secret_key is None or len(self.secret_key.get_secret_value().strip()) < 32:
                raise ValueError("production requires a signing secret of at least 32 characters")
        return self


def load_settings(environ: Mapping[str, str]) -> Settings:
    allowed = {
        "PAYPROOF_ENV",
        "PAYPROOF_PORT",
        "PAYPROOF_DATA_DIR",
        "PAYPROOF_EXTRACTION_MODE",
        "PAYPROOF_SECRET_KEY",
        "PAYPROOF_OPERATOR_TOKEN",
        "PAYPROOF_PROVIDER_API_KEY",
        "PAYPROOF_PROVIDER",
        "PAYPROOF_PUBLIC_LIVE_ENABLED",
        "PAYPROOF_PUBLIC_LIVE_MAX_CALLS",
        "PAYPROOF_PROVIDER_BASE_URL",
        "PAYPROOF_PROVIDER_MODEL",
        "PAYPROOF_EXTRACTION_TIMEOUT_SECONDS",
    }
    if any(key.startswith("PAYPROOF_") and key not in allowed for key in environ):
        raise ConfigurationError("Unknown PAYPROOF environment variable; consult .env.example")
    if environ.get("PAYPROOF_PUBLIC_LIVE_ENABLED", "false") not in {"true", "false"}:
        raise ConfigurationError("PAYPROOF_PUBLIC_LIVE_ENABLED must be true or false")
    raw_cap = environ.get("PAYPROOF_PUBLIC_LIVE_MAX_CALLS", "20")
    if not raw_cap.isascii() or not raw_cap.isdecimal():
        raise ConfigurationError("PAYPROOF_PUBLIC_LIVE_MAX_CALLS must contain ASCII digits")
    raw_port = environ.get("PAYPROOF_PORT", "8000")
    if not raw_port.isascii() or not raw_port.isdecimal():
        raise ConfigurationError("PAYPROOF_PORT must contain ASCII digits")
    raw_secret = environ.get("PAYPROOF_SECRET_KEY", "")
    raw_api_key = environ.get("PAYPROOF_PROVIDER_API_KEY", "")
    raw_model = environ.get("PAYPROOF_PROVIDER_MODEL", "")
    raw_timeout = environ.get("PAYPROOF_EXTRACTION_TIMEOUT_SECONDS", "30")
    if not raw_timeout.isascii() or not raw_timeout.isdecimal():
        raise ConfigurationError("PAYPROOF_EXTRACTION_TIMEOUT_SECONDS must contain ASCII digits")
    raw_dir = environ.get("PAYPROOF_DATA_DIR", "./data")
    if not raw_dir.strip():
        raise ConfigurationError("PAYPROOF_DATA_DIR must not be empty")
    try:
        return Settings.model_validate(
            {
                "environment": environ.get("PAYPROOF_ENV", "development"),
                "port": int(raw_port),
                "data_dir": Path(raw_dir),
                "extraction_mode": environ.get("PAYPROOF_EXTRACTION_MODE", "disabled"),
                "secret_key": SecretStr(raw_secret) if raw_secret else None,
                "operator_token": SecretStr(environ["PAYPROOF_OPERATOR_TOKEN"])
                if environ.get("PAYPROOF_OPERATOR_TOKEN")
                else None,
                "public_live_enabled": environ.get("PAYPROOF_PUBLIC_LIVE_ENABLED", "false")
                == "true",
                "public_live_max_calls": int(raw_cap),
                "provider": environ.get("PAYPROOF_PROVIDER", "openai"),
                "provider_base_url": environ.get("PAYPROOF_PROVIDER_BASE_URL") or None,
                "provider_api_key": SecretStr(raw_api_key) if raw_api_key else None,
                "provider_model": raw_model or None,
                "extraction_timeout_seconds": int(raw_timeout),
            }
        )
    except ValidationError:
        raise ConfigurationError(
            "Invalid PayProof settings; check allowed values, live provider configuration, and the production signing-secret requirement"
        ) from None
