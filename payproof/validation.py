"""Typed JSON boundary; CaseContract additionally enforces source grounding."""

from typing import TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def parse_contract(model: type[ModelT], raw_json: str | bytes) -> ModelT:
    return model.model_validate_json(raw_json)
