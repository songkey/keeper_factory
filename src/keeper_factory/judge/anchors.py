from __future__ import annotations

from pathlib import Path

from pydantic import Field

from keeper_factory.memory.yaml_io import load_yaml_dict
from keeper_factory.schemas.base import StrictModel
from keeper_factory.schemas.enums import Verdict


class AnchorExample(StrictModel):
    case_id: str
    expected_verdict: Verdict
    violation_types: list[str] = Field(default_factory=list)
    notes: str | None = None


class AnchorSet(StrictModel):
    version: str
    examples: list[AnchorExample] = Field(default_factory=list)

    def render_few_shot(self, *, limit: int = 5) -> str:
        if not self.examples:
            return "(no anchor examples configured)"
        chunks: list[str] = []
        for example in self.examples[:limit]:
            line = f"- case={example.case_id}, expected={example.expected_verdict.value}"
            if example.violation_types:
                line += f", violations={','.join(example.violation_types)}"
            if example.notes:
                line += f" — {example.notes}"
            chunks.append(line)
        return "\n".join(chunks)


def default_anchor_path(data_root: Path) -> Path:
    return data_root / "goldenset" / "anchors" / "anchor_v0.yaml"


def load_anchor_set(data_root: Path, *, version: str = "anchor_v0") -> AnchorSet:
    path = data_root / "goldenset" / "anchors" / f"{version}.yaml"
    if not path.is_file():
        return AnchorSet(version=version, examples=[])
    data = load_yaml_dict(path)
    return AnchorSet.model_validate(data)
