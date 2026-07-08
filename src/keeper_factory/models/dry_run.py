from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from keeper_factory.util.hashing import canonical_json, sha256_hex


class FixtureNotFoundError(FileNotFoundError):
    pass


ResponseType = Literal["text", "image"]


@dataclass(frozen=True)
class FixtureRequest:
    node: str
    model_name: str
    system_prompt: str
    user_prompt: str
    image_hashes: list[str] = field(default_factory=list)

    def request_key(self) -> str:
        payload = {
            "node": self.node,
            "model_name": self.model_name,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "image_hashes": sorted(self.image_hashes),
        }
        return sha256_hex(canonical_json(payload))


@dataclass
class FixtureResponse:
    response_type: ResponseType
    text: str | None = None
    image_relpath: str | None = None
    token_usage: dict[str, int | None] | None = None


class FixtureStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _fixture_path(self, node: str, request_key: str) -> Path:
        return self.root / node / f"{request_key}.json"

    def load(self, request: FixtureRequest) -> FixtureResponse | None:
        path = self._fixture_path(request.node, request.request_key())
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return FixtureResponse(
            response_type=raw["response_type"],
            text=raw.get("text"),
            image_relpath=raw.get("image_relpath"),
            token_usage=raw.get("token_usage"),
        )

    def require(self, request: FixtureRequest) -> FixtureResponse:
        fixture = self.load(request)
        if fixture is None:
            raise FixtureNotFoundError(
                f"No fixture for node={request.node!r} key={request.request_key()}"
            )
        return fixture

    def save(self, request: FixtureRequest, response: FixtureResponse) -> Path:
        node_dir = self.root / request.node
        node_dir.mkdir(parents=True, exist_ok=True)
        path = self._fixture_path(request.node, request.request_key())
        payload: dict[str, Any] = {
            "node": request.node,
            "request_key": request.request_key(),
            "response_type": response.response_type,
            "token_usage": response.token_usage,
        }
        if response.text is not None:
            payload["text"] = response.text
        if response.image_relpath is not None:
            payload["image_relpath"] = response.image_relpath
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def image_path(self, relpath: str) -> Path:
        return self.root / relpath

    def save_image(self, request: FixtureRequest, image_bytes: bytes, *, suffix: str = "png") -> str:
        relpath = f"{request.node}/{request.request_key()}.{suffix}"
        path = self.image_path(relpath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image_bytes)
        return relpath
