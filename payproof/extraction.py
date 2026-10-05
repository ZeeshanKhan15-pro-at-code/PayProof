"""Validate and source-ground extraction; never compare or authorize payment."""

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from payproof.config import Settings, load_settings
from payproof.extraction_contract import PROMPT_VERSION, WireExtractionPayload
from payproof.openai_extraction import FailureCode, OpenAIExtractionProvider, ProviderFailure
from payproof.provenance import account_quote_is_complete
from payproof.schemas import (
    EVIDENCE_FIELDS,
    CaseContract,
    ExtractionMetadata,
    PaymentRequestEvidence,
    SourceDocument,
)
from payproof.validation import parse_contract


class ExtractionInputError(ValueError):
    """Invalid source snapshots are rejected before any external request."""


@dataclass(frozen=True)
class ExtractionAttempt:
    evidence: PaymentRequestEvidence = field(repr=False)
    source_digests: tuple[tuple[UUID, str], ...]
    raw_provider_response: bytes | None = field(default=None, repr=False)


def _validate_sources(sources: tuple[SourceDocument, ...]) -> tuple[SourceDocument, ...]:
    if not isinstance(sources, tuple) or any(
        not isinstance(source, SourceDocument) for source in sources
    ):
        raise ExtractionInputError("Expected a tuple of validated source documents")
    if not sources or len(sources) > 16 or len({s.source_id for s in sources}) != len(sources):
        raise ExtractionInputError("Expected 1-16 unique source snapshots")
    try:
        sources = tuple(
            SourceDocument.model_validate_json(source.model_dump_json()) for source in sources
        )
    except ValidationError:
        raise ExtractionInputError("Invalid source snapshot") from None
    if sum(len(source.text) for source in sources) > 20_000:
        raise ExtractionInputError("Total source text exceeds 20,000 characters")
    if any(source.captured_at > datetime.now(UTC) for source in sources):
        raise ExtractionInputError("Source capture cannot be in the future")
    return sources


def _record(
    fields: dict[str, Any],
    sources: tuple[SourceDocument, ...],
    metadata: ExtractionMetadata,
    request_id: UUID,
) -> PaymentRequestEvidence:
    evidence = PaymentRequestEvidence.model_validate_json(
        json.dumps(
            {
                **fields,
                "request_id": str(request_id),
                "source_ids": [str(s.source_id) for s in sources],
                "extraction": metadata.model_dump(mode="json"),
            }
        )
    )
    CaseContract(sources=sources, evidence=evidence, baseline=None)
    return evidence


def _ground_wire(
    wire: WireExtractionPayload, sources: tuple[SourceDocument, ...]
) -> dict[str, Any]:
    by_id = {source.source_id: source for source in sources}
    fields: dict[str, Any] = {}
    if sum(len(getattr(wire, name).candidates) for name in EVIDENCE_FIELDS) > 64:
        raise ProviderFailure("INVALID_RESPONSE")
    for name in EVIDENCE_FIELDS:
        observation = getattr(wire, name)
        candidates: list[dict[str, Any]] = []
        for candidate in observation.candidates:
            source = by_id.get(candidate.source_id)
            excerpt = candidate.exact_excerpt
            if source is None or candidate.raw_text not in excerpt:
                raise ProviderFailure("EVIDENCE_INVALID")
            start = source.text.find(excerpt)
            if start < 0 or source.text.find(excerpt, start + 1) >= 0:
                raise ProviderFailure("EVIDENCE_INVALID")
            if isinstance(candidate.value, str) and candidate.value != candidate.raw_text:
                raise ProviderFailure("EVIDENCE_INVALID")
            if name == "account_identifier" and not account_quote_is_complete(
                source.text, candidate.raw_text, start, start + len(excerpt)
            ):
                raise ProviderFailure("EVIDENCE_INVALID")
            candidates.append(
                {
                    "value": candidate.value,
                    "evidence": {
                        "evidence_id": str(uuid4()),
                        "source_id": str(source.source_id),
                        "field": name,
                        "extracted_value": candidate.raw_text,
                        "exact_excerpt": excerpt,
                        "location": {
                            "char_start": start,
                            "char_end": start + len(excerpt),
                            "page_number": source.page_number,
                        },
                        "extraction_status": observation.status,
                    },
                }
            )
        fields[name] = {"status": observation.status, "candidates": candidates}
    return fields


def _fixture_fields(sources: tuple[SourceDocument, ...]) -> tuple[dict[str, Any], str] | None:
    from payproof.fixtures import load_corpus

    if len(sources) != 1:
        return None
    source = sources[0]
    for fixture in load_corpus().requests:
        if (fixture.source.kind, fixture.source.text) != (source.kind, source.text):
            continue
        fields: dict[str, Any] = {
            name: getattr(fixture.evidence, name).model_dump(mode="json")
            for name in EVIDENCE_FIELDS
        }
        for observation in fields.values():
            for candidate in observation["candidates"]:
                span = candidate["evidence"]
                span["source_id"] = str(source.source_id)
                span["evidence_id"] = str(uuid4())
                span["location"]["page_number"] = source.page_number
        return fields, fixture.evidence.extraction.operator_id or "synthetic-fixture-author"
    return None


def extract_attempt(
    sources: tuple[SourceDocument, ...],
    *,
    settings: Settings | None = None,
    request_id: UUID | None = None,
) -> ExtractionAttempt:
    """One bounded attempt with private audit bytes and a canonical failure record."""
    sources = _validate_sources(sources)
    if request_id is not None and not isinstance(request_id, UUID):
        raise ExtractionInputError("Request ID must be a UUID")
    settings = settings if settings is not None else load_settings(os.environ)
    if settings.extraction_mode == "live" and settings.provider_api_key is not None:
        credential = settings.provider_api_key.get_secret_value()
        if credential and any(credential in source.text for source in sources):
            raise ExtractionInputError("Source contains the configured provider credential")
    request_id = request_id if request_id is not None else uuid4()
    metadata = ExtractionMetadata(
        attempt_id=uuid4(),
        method="NOT_ATTEMPTED",
        extracted_at=datetime.now(UTC),
        schema_version="1",
        failure_code="NOT_CONFIGURED",
    )
    raw: bytes | None = None
    fields: dict[str, Any] | None = None
    failure: FailureCode | None = "NOT_CONFIGURED"
    if settings.extraction_mode == "fixture":
        fixture = _fixture_fields(sources)
        if fixture is not None:
            fields, operator = fixture
            metadata = ExtractionMetadata(
                attempt_id=metadata.attempt_id,
                method="FIXTURE",
                extracted_at=metadata.extracted_at,
                schema_version="1",
                operator_id=operator,
            )
            failure = None
    elif settings.extraction_mode == "live":
        assert settings.provider_api_key is not None and settings.provider_model is not None
        metadata = ExtractionMetadata(
            attempt_id=metadata.attempt_id,
            method="AI",
            extracted_at=metadata.extracted_at,
            schema_version="1",
            provider="openai",
            model=settings.provider_model,
            prompt_version=PROMPT_VERSION,
        )
        provider = OpenAIExtractionProvider(
            api_key=settings.provider_api_key,
            model=settings.provider_model,
            timeout_seconds=settings.extraction_timeout_seconds,
        )
        try:
            completion = provider.complete(sources)
            raw = completion.raw_response
            wire = parse_contract(WireExtractionPayload, completion.text)
            fields = _ground_wire(wire, sources)
            metadata = ExtractionMetadata(
                attempt_id=metadata.attempt_id,
                method="AI",
                extracted_at=metadata.extracted_at,
                schema_version="1",
                provider="openai",
                model=completion.model,
                prompt_version=PROMPT_VERSION,
            )
            failure = None
        except ProviderFailure as error:
            failure = error.code
            raw = error.raw_response if error.raw_response is not None else raw
        except ValueError:
            failure = "INVALID_RESPONSE"
    if failure is None and fields is not None:
        try:
            evidence = _record(fields, sources, metadata, request_id)
            return ExtractionAttempt(
                evidence=evidence,
                source_digests=tuple((source.source_id, source.sha256) for source in sources),
                raw_provider_response=raw,
            )
        except ValidationError:
            failure = "INVALID_RESPONSE"
    metadata_values = metadata.model_dump()
    metadata_values["failure_code"] = failure or "INVALID_RESPONSE"
    metadata = ExtractionMetadata.model_validate(metadata_values)
    fields = {name: {"status": "UNREADABLE", "candidates": []} for name in EVIDENCE_FIELDS}
    evidence = _record(fields, sources, metadata, request_id)
    return ExtractionAttempt(
        evidence=evidence,
        source_digests=tuple((s.source_id, s.sha256) for s in sources),
        raw_provider_response=raw,
    )


def extract_documents(
    sources: tuple[SourceDocument, ...],
    *,
    settings: Settings | None = None,
    request_id: UUID | None = None,
) -> PaymentRequestEvidence:
    return extract_attempt(sources, settings=settings, request_id=request_id).evidence


def extract_document(
    source: SourceDocument, *, settings: Settings | None = None, request_id: UUID | None = None
) -> PaymentRequestEvidence:
    return extract_documents((source,), settings=settings, request_id=request_id)
