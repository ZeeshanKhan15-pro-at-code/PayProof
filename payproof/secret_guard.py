"""Reject literal configured secrets at data boundaries, without echoing values."""

from collections.abc import Mapping

from payproof.config import Settings


def reject_configured_secrets(value: object, settings: Settings) -> None:
    secrets = tuple(
        secret.get_secret_value()
        for secret in (settings.provider_api_key, settings.secret_key, settings.operator_token)
        if secret is not None and secret.get_secret_value()
    )
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if any(secret in item for secret in secrets):
                raise ValueError("configured credential in workflow data")
        elif isinstance(item, Mapping):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
