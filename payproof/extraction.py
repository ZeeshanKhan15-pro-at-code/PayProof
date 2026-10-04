"""Reserved extraction boundary: add one bounded provider adapter in the next slice.

Offline labeled evidence comes from fixtures.py. It must never masquerade as a
live provider response. AI may produce ExtractionPayload only, never decisions.
"""

from payproof.schemas import ExtractionPayload, SourceDocument


def extract_document(source: SourceDocument) -> ExtractionPayload:
    raise NotImplementedError("Live structured extraction is not implemented")
