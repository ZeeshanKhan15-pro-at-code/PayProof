"""One bounded, synchronous Responses API adapter over standard-library HTTPS."""

import json
from dataclasses import dataclass, field
from http.client import HTTPException, HTTPMessage
from typing import IO, Literal
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, SecretStr

from payproof.extraction_contract import EXTRACTION_INSTRUCTIONS, structured_output_schema
from payproof.schemas import ShortText, SourceDocument
from payproof.validation import parse_contract

MAX_PROVIDER_BYTES = 262_144
MAX_OUTPUT_TOKENS = 8_000
API_URL = "https://api.openai.com/v1/responses"
FailureCode = Literal[
    "TIMEOUT", "PROVIDER_UNAVAILABLE", "INVALID_RESPONSE", "EVIDENCE_INVALID", "NOT_CONFIGURED"
]


class ProviderFailure(Exception):
    def __init__(self, code: FailureCode, raw_response: bytes | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.raw_response = raw_response


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: IO[bytes], code: int, msg: str, headers: HTTPMessage, newurl: str
    ) -> None:
        return None


class _Content(BaseModel):
    model_config = ConfigDict(strict=True)
    type: Literal["output_text", "refusal"]
    text: str | None = None


class _Output(BaseModel):
    model_config = ConfigDict(strict=True)
    type: Literal["message", "reasoning"]
    role: Literal["assistant"] | None = None
    status: str | None = None
    content: tuple[_Content, ...] = ()


class _Response(BaseModel):
    model_config = ConfigDict(strict=True)
    status: Literal["completed"]
    model: ShortText
    output: tuple[_Output, ...]
    error: None = None
    incomplete_details: None = None


@dataclass(frozen=True)
class ProviderCompletion:
    text: str = field(repr=False)
    model: str
    raw_response: bytes = field(repr=False)


@dataclass(frozen=True)
class OpenAIExtractionProvider:
    api_key: SecretStr = field(repr=False)
    model: str
    timeout_seconds: int = 30

    def complete(self, sources: tuple[SourceDocument, ...]) -> ProviderCompletion:
        body = {
            "model": self.model,
            "instructions": EXTRACTION_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "documents": [
                                {
                                    "source_id": str(source.source_id),
                                    "kind": source.kind,
                                    "text": source.text,
                                }
                                for source in sources
                            ]
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "payment_request_observations",
                    "strict": True,
                    "schema": structured_output_schema(),
                }
            },
            "tools": [],
            "store": False,
            "stream": False,
            "background": False,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        }
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_PROVIDER_BYTES:
            raise ProviderFailure("INVALID_RESPONSE")
        request = Request(
            API_URL,
            data=encoded,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
        )
        try:
            with build_opener(_NoRedirect()).open(
                request, timeout=self.timeout_seconds
            ) as response:
                raw = response.read(MAX_PROVIDER_BYTES + 1)
        except TimeoutError:
            raise ProviderFailure("TIMEOUT") from None
        except HTTPError:
            raise ProviderFailure("PROVIDER_UNAVAILABLE") from None
        except URLError as error:
            code: FailureCode = (
                "TIMEOUT" if isinstance(error.reason, TimeoutError) else "PROVIDER_UNAVAILABLE"
            )
            raise ProviderFailure(code) from None
        except (OSError, HTTPException):
            raise ProviderFailure("PROVIDER_UNAVAILABLE") from None
        if len(raw) > MAX_PROVIDER_BYTES:
            raise ProviderFailure("INVALID_RESPONSE")
        try:
            parsed = parse_contract(_Response, raw)
        except ValueError:
            raise ProviderFailure("INVALID_RESPONSE", raw) from None
        texts: list[str] = []
        for item in parsed.output:
            if item.type == "reasoning":
                continue
            if item.role != "assistant" or item.status != "completed":
                raise ProviderFailure("INVALID_RESPONSE", raw)
            for content in item.content:
                if content.type != "output_text" or content.text is None:
                    raise ProviderFailure("INVALID_RESPONSE", raw)
                texts.append(content.text)
        if len(texts) != 1:
            raise ProviderFailure("INVALID_RESPONSE", raw)
        return ProviderCompletion(text=texts[0], model=parsed.model, raw_response=raw)
