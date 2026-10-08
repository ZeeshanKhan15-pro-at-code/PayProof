"""Bounded model-catalog diagnostic; emits status only, never response bodies/keys."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from payproof.config import ConfigurationError, load_settings
from payproof.openai_extraction import MAX_PROVIDER_BYTES, _NoRedirect, _reject_credential_echo


def main() -> int:
    try:
        settings = load_settings(os.environ)
    except ConfigurationError:
        print(json.dumps({"status": "NOT_CONFIGURED"}))
        return 2
    if settings.extraction_mode != "live" or settings.provider_api_key is None:
        print(json.dumps({"status": "NOT_CONFIGURED"}))
        return 2
    base = settings.provider_base_url or (
        "https://api.featherless.ai/v1"
        if settings.provider == "featherless"
        else "https://api.openai.com/v1"
    )
    request = Request(
        base.rstrip("/") + "/models",
        headers={"Authorization": "Bearer " + settings.provider_api_key.get_secret_value()},
    )
    try:
        with build_opener(_NoRedirect()).open(
            request, timeout=settings.extraction_timeout_seconds
        ) as response:
            raw = response.read(MAX_PROVIDER_BYTES + 1)
        if len(raw) > MAX_PROVIDER_BYTES:
            print(json.dumps({"status": "CATALOG_TOO_LARGE"}))
            return 1
        _reject_credential_echo(raw, settings.provider_api_key.get_secret_value())
        data = json.loads(raw)
        found = any(model.get("id") == settings.provider_model for model in data["data"])
        print(
            json.dumps(
                {
                    "status": "MODEL_LISTED" if found else "MODEL_NOT_LISTED",
                    "provider": settings.provider,
                    "model": settings.provider_model,
                    "exact_id_present": found,
                }
            )
        )
        return 0 if found else 1
    except HTTPError as error:
        print(
            json.dumps(
                {
                    "status": "PROVIDER_HTTP_ERROR",
                    "http_status": error.code,
                    "network_policy_blocked": bool(
                        error.headers and error.headers.get("X-Mitmproxy-Blocked-Reason")
                    ),
                }
            )
        )
    except URLError:
        print(json.dumps({"status": "NETWORK_UNAVAILABLE"}))
    except TimeoutError:
        print(json.dumps({"status": "TIMEOUT"}))
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({"status": "INVALID_OR_UNAVAILABLE_CATALOG"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
