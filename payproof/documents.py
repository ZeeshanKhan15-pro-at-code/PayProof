"""Pasted-text source capture only: no attachment, link, PDF, or OCR ingestion."""

from datetime import datetime, timezone
from uuid import uuid4

from payproof.provenance import source_digest
from payproof.schemas import SourceDocument, SourceKind


def capture_text(
    text: str, *, operator_id: str, kind: SourceKind = "PLAIN_TEXT", label: str | None = None
) -> SourceDocument:
    return SourceDocument(
        source_id=uuid4(), kind=kind, text=text, sha256=source_digest(text),
        captured_at=datetime.now(timezone.utc), captured_by=operator_id, label=label,
    )
