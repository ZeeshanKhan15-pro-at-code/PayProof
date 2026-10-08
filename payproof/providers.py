"""Provider-specific wire protocols behind one extraction-only boundary."""

import json
from dataclasses import dataclass, field
from http.client import HTTPException
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request

from pydantic import SecretStr

from payproof import openai_extraction as transport
from payproof.config import Settings
from payproof.extraction_contract import EXTRACTION_INSTRUCTIONS, structured_output_schema
from payproof.openai_extraction import ProviderCompletion, ProviderFailure
from payproof.schemas import SourceDocument
from payproof.validation import validate_json_syntax


class ExtractionProvider(Protocol):
    def complete(self, sources: tuple[SourceDocument, ...]) -> ProviderCompletion: ...


@dataclass(frozen=True)
class FeatherlessExtractionProvider:
    api_key: SecretStr = field(repr=False)
    model: str
    base_url: str = "https://api.featherless.ai/v1"
    timeout_seconds: int = 30

    def complete(self, sources: tuple[SourceDocument, ...]) -> ProviderCompletion:
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": EXTRACTION_INSTRUCTIONS
                    + "\nJSON schema:\n"
                    + json.dumps(structured_output_schema()),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "documents": [
                                {"source_id": str(s.source_id), "kind": s.kind, "text": s.text}
                                for s in sources
                            ]
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
            "temperature": 0,
            "max_tokens": transport.MAX_OUTPUT_TOKENS,
        }
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if len(encoded) > transport.MAX_PROVIDER_BYTES:
            raise ProviderFailure("INVALID_RESPONSE")
        request = Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=encoded,
            headers={
                "Authorization": "Bearer " + self.api_key.get_secret_value(),
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with transport.build_opener(transport._NoRedirect()).open(
                request, timeout=self.timeout_seconds
            ) as response:
                raw = response.read(transport.MAX_PROVIDER_BYTES + 1)
        except TimeoutError:
            raise ProviderFailure("TIMEOUT") from None
        except HTTPError:
            raise ProviderFailure("PROVIDER_UNAVAILABLE") from None
        except URLError as error:
            raise ProviderFailure(
                "TIMEOUT" if isinstance(error.reason, TimeoutError) else "PROVIDER_UNAVAILABLE"
            ) from None
        except (OSError, HTTPException):
            raise ProviderFailure("PROVIDER_UNAVAILABLE") from None
        if len(raw) > transport.MAX_PROVIDER_BYTES:
            raise ProviderFailure("INVALID_RESPONSE")
        transport._reject_credential_echo(raw, self.api_key.get_secret_value())
        try:
            validate_json_syntax(raw)
            envelope = json.loads(raw)
            choices = envelope["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            choice = choices[0]
            message = choice["message"]
            text = message["content"]
            model = envelope["model"]
            if (
                choice["finish_reason"] != "stop"
                or message["role"] != "assistant"
                or message.get("tool_calls")
                or message.get("function_call")
                or message.get("refusal")
                or not isinstance(text, str)
                or not isinstance(model, str)
                or not model.strip()
                or len(model) > 256
            ):
                raise ValueError
            validate_json_syntax(text)
        except (ValueError, TypeError, KeyError, IndexError):
            raise ProviderFailure("INVALID_RESPONSE") from None
        return ProviderCompletion(text=text, model=model, raw_response=raw)


def create_provider(settings: Settings) -> ExtractionProvider:
    assert settings.provider_api_key is not None and settings.provider_model is not None
    if settings.provider == "featherless":
        return FeatherlessExtractionProvider(
            settings.provider_api_key,
            settings.provider_model,
            settings.provider_base_url or "https://api.featherless.ai/v1",
            settings.extraction_timeout_seconds,
        )
    return transport.OpenAIExtractionProvider(
        settings.provider_api_key,
        settings.provider_model,
        settings.extraction_timeout_seconds,
        settings.provider_base_url or "https://api.openai.com/v1",
    )
