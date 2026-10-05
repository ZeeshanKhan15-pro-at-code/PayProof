"""Typed JSON boundary; CaseContract additionally enforces source grounding."""

import json
from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def validate_json_syntax(raw_json: str | bytes) -> None:
    """Reject ambiguous object keys before a parser can silently overwrite them."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def nonfinite_constant(value: str) -> None:
        raise ValueError("nonfinite values are not JSON")

    try:
        json.loads(raw_json, object_pairs_hook=unique_object, parse_constant=nonfinite_constant)
    except (RecursionError, UnicodeDecodeError):
        raise ValueError("invalid JSON encoding or nesting") from None


def parse_contract(model: type[ModelT], raw_json: str | bytes) -> ModelT:
    validate_json_syntax(raw_json)
    return model.model_validate_json(raw_json)
