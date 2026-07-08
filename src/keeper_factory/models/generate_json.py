from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


class ParseFailureError(RuntimeError):
    """JSON generation/validation failed after repair retry."""

    def __init__(self, message: str, *, raw_output: str, validation_error: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output
        self.validation_error = validation_error


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return text
    match = _JSON_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def schema_prompt_appendix(schema_model: type[BaseModel]) -> str:
    schema = schema_model.model_json_schema()
    return (
        "\n\nRespond with a single JSON object that conforms to this schema "
        "(no markdown, no commentary):\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )


def repair_prompt(*, raw_output: str, validation_error: str, schema_model: type[BaseModel]) -> str:
    return (
        "Your previous response was not valid JSON for the required schema.\n"
        f"Validation error:\n{validation_error}\n\n"
        f"Previous output:\n{raw_output}\n\n"
        "Return ONLY corrected JSON that satisfies the schema:\n"
        f"{json.dumps(schema_model.model_json_schema(), ensure_ascii=False, indent=2)}"
    )


@dataclass
class GenerateJsonResult:
    data: BaseModel
    raw_output: str
    repair_attempted: bool = False


def parse_and_validate(raw: str, schema_model: type[BaseModel]) -> BaseModel:
    json_text = extract_json_text(raw)
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    return schema_model.model_validate(payload)
