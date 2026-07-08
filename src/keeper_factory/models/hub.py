from __future__ import annotations

import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar

import numpy as np
from PIL import Image
from pydantic import BaseModel

from keeper_factory.config import LoadedConfig, NodeConfig, NodeName
from keeper_factory.models.dry_run import FixtureNotFoundError, FixtureRequest, FixtureResponse, FixtureStore
from keeper_factory.models.generate_json import (
    GenerateJsonResult,
    ParseFailureError,
    parse_and_validate,
    repair_prompt,
    schema_prompt_appendix,
)
from keeper_factory.models.llm_api import ImageEditAPI, LLMAPI, VLLMAPI
from keeper_factory.models.token_tracker import TokenTracker
from keeper_factory.util.hashing import sha256_hex

T = TypeVar("T", bound=BaseModel)

NodeApiKind = Literal["vlm", "llm", "edit"]

NODE_API_KIND: dict[NodeName, NodeApiKind] = {
    "f1_candidate": "vlm",
    "f2_edit_prompt": "vlm",
    "f2_image_edit": "edit",
    "judge_redline": "vlm",
    "judge_quality": "vlm",
    "judge_pairwise": "vlm",
    "f4_synthesis": "llm",
    "f4_refine": "llm",
    "f5_report": "llm",
}


@dataclass(frozen=True)
class ResolvedNode:
    name: NodeName
    api_kind: NodeApiKind
    model_name: str
    options: NodeConfig


@dataclass
class ModelHub:
    loaded: LoadedConfig
    dry_run: bool = False
    record_fixtures: bool = False
    fixtures_dir: Path | None = None
    token_tracker: TokenTracker | None = None

    def __post_init__(self) -> None:
        if self.fixtures_dir is None:
            self.fixtures_dir = self.loaded.project_root / "tests" / "fixtures" / "llm"
        if self.token_tracker is None:
            self.token_tracker = TokenTracker()
        self._fixtures = FixtureStore(self.fixtures_dir)
        self._llm_clients: dict[str, LLMAPI] = {}
        self._vlm_clients: dict[str, VLLMAPI] = {}
        self._edit_clients: dict[str, ImageEditAPI] = {}

    @classmethod
    def from_loaded(
        cls,
        loaded: LoadedConfig,
        *,
        dry_run: bool = False,
        record_fixtures: bool = False,
        fixtures_dir: Path | None = None,
    ) -> ModelHub:
        return cls(
            loaded=loaded,
            dry_run=dry_run,
            record_fixtures=record_fixtures,
            fixtures_dir=fixtures_dir,
        )

    def resolve_node(self, node: NodeName) -> ResolvedNode:
        cfg = self.loaded.config
        node_cfg = getattr(cfg.models.nodes, node)
        defaults = cfg.models.defaults
        if node == "f2_image_edit":
            model_name = node_cfg.model_name or defaults.edit
        else:
            model_name = node_cfg.model_name or defaults.vlm
        return ResolvedNode(
            name=node,
            api_kind=NODE_API_KIND[node],
            model_name=model_name,
            options=node_cfg,
        )

    def _api_common_kwargs(self, resolved: ResolvedNode) -> dict[str, Any]:
        api = self.loaded.config.models.api
        opts = resolved.options
        kwargs: dict[str, Any] = {
            "api_key": self.loaded.secrets.api_key if self.loaded.secrets else "",
            "request_url": api.request_url,
            "model_name": resolved.model_name,
            "timeout_seconds": api.timeout_seconds,
            "thinking_enabled": bool(opts.thinking),
            "reasoning_effort": opts.reasoning_effort,
            "max_tokens": opts.max_tokens,
        }
        if resolved.api_kind == "edit":
            kwargs["timeout_seconds"] = api.image_edit_timeout_seconds
        return kwargs

    def _get_llm(self, resolved: ResolvedNode) -> LLMAPI:
        key = resolved.model_name
        if key not in self._llm_clients:
            self._llm_clients[key] = LLMAPI(**self._api_common_kwargs(resolved))
        return self._llm_clients[key]

    def _get_vlm(self, resolved: ResolvedNode) -> VLLMAPI:
        key = resolved.model_name
        if key not in self._vlm_clients:
            self._vlm_clients[key] = VLLMAPI(**self._api_common_kwargs(resolved))
        return self._vlm_clients[key]

    def _get_edit(self, resolved: ResolvedNode) -> ImageEditAPI:
        key = resolved.model_name
        if key not in self._edit_clients:
            self._edit_clients[key] = ImageEditAPI(**self._api_common_kwargs(resolved))
        return self._edit_clients[key]

    @staticmethod
    def _image_hashes(images: list[np.ndarray] | None) -> list[str]:
        if not images:
            return []
        hashes: list[str] = []
        for image in images:
            array = np.asarray(image)
            hashes.append(sha256_hex(array.tobytes()))
        return hashes

    def _fixture_request(
        self,
        resolved: ResolvedNode,
        *,
        system_prompt: str,
        user_prompt: str,
        images: list[np.ndarray] | None = None,
    ) -> FixtureRequest:
        return FixtureRequest(
            node=resolved.name,
            model_name=resolved.model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_hashes=self._image_hashes(images),
        )

    def _record_token_usage(self, resolved: ResolvedNode, usage: dict[str, int | None] | None) -> None:
        if self.token_tracker is None or not usage:
            return
        if resolved.api_kind == "edit":
            self.token_tracker.record_edit_call(resolved.model_name, usage)
        else:
            self.token_tracker.record_vlm_call(resolved.model_name, usage)

    def generate_text(
        self,
        *,
        node: NodeName,
        user_prompt: str,
        system_prompt: str = "",
        images: list[np.ndarray] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        resolved = self.resolve_node(node)
        request = self._fixture_request(
            resolved,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            images=images,
        )

        if self.dry_run:
            fixture = self._fixtures.require(request)
            if fixture.token_usage:
                self._record_token_usage(resolved, fixture.token_usage)
            if fixture.response_type != "text" or fixture.text is None:
                raise FixtureNotFoundError(f"Fixture for {node} is not text")
            return fixture.text

        if resolved.api_kind == "llm":
            client = self._get_llm(resolved)
            text = client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )
            usage = client.consume_token_usage()
        elif resolved.api_kind == "vlm":
            client = self._get_vlm(resolved)
            if not images:
                raise ValueError(f"node {node} requires images")
            max_long_edge = resolved.options.max_long_edge or 768
            text = client.generate(
                images=images,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_long_edge=max_long_edge,
                max_tokens=max_tokens,
            )
            usage = client.consume_token_usage()
        else:
            raise ValueError(f"node {node} is not a text generation node")

        self._record_token_usage(resolved, usage)
        if self.record_fixtures:
            self._fixtures.save(
                request,
                FixtureResponse(response_type="text", text=text, token_usage=usage),
            )
        return text

    def generate_json(
        self,
        *,
        node: NodeName,
        schema: type[T],
        user_prompt: str,
        system_prompt: str = "",
        images: list[np.ndarray] | None = None,
        max_tokens: int | None = None,
    ) -> GenerateJsonResult:
        prompt_with_schema = user_prompt + schema_prompt_appendix(schema)
        raw = self.generate_text(
            node=node,
            system_prompt=system_prompt,
            user_prompt=prompt_with_schema,
            images=images,
            max_tokens=max_tokens,
        )
        try:
            data = parse_and_validate(raw, schema)
            return GenerateJsonResult(data=data, raw_output=raw, repair_attempted=False)
        except ValueError as first_error:
            repair_user_prompt = repair_prompt(
                raw_output=raw,
                validation_error=str(first_error),
                schema_model=schema,
            )
            repaired_raw = self.generate_text(
                node=node,
                system_prompt=system_prompt,
                user_prompt=repair_user_prompt,
                images=images,
                max_tokens=max_tokens,
            )
            try:
                data = parse_and_validate(repaired_raw, schema)
                return GenerateJsonResult(
                    data=data, raw_output=repaired_raw, repair_attempted=True
                )
            except ValueError as second_error:
                raise ParseFailureError(
                    f"JSON parse/validate failed for node {node}",
                    raw_output=repaired_raw,
                    validation_error=str(second_error),
                ) from second_error

    def image_edit(
        self,
        *,
        node: NodeName,
        image: Image.Image,
        prompt: str,
    ) -> Image.Image:
        if node != "f2_image_edit":
            raise ValueError(f"image_edit only supported on f2_image_edit, got {node}")
        resolved = self.resolve_node(node)
        request = self._fixture_request(
            resolved, system_prompt="", user_prompt=prompt, images=None
        )

        if self.dry_run:
            fixture = self._fixtures.require(request)
            if fixture.token_usage:
                self._record_token_usage(resolved, fixture.token_usage)
            if fixture.response_type != "image" or not fixture.image_relpath:
                raise FixtureNotFoundError(f"Fixture for {node} is not image")
            path = self._fixtures.image_path(fixture.image_relpath)
            return Image.open(path).convert("RGB")

        client = self._get_edit(resolved)
        result = client.image_edit(image=image, prompt=prompt)
        usage = client.consume_token_usage()
        self._record_token_usage(resolved, usage)

        if self.record_fixtures:
            buf = io.BytesIO()
            result.save(buf, format="PNG")
            relpath = self._fixtures.save_image(request, buf.getvalue())
            self._fixtures.save(
                request,
                FixtureResponse(
                    response_type="image",
                    image_relpath=relpath,
                    token_usage=usage,
                ),
            )
        return result

    def env_model_labels(self) -> dict[str, str]:
        """Model names to write into experiment env fields."""
        return {
            "vlm": self.resolve_node("f1_candidate").model_name,
            "edit_model": self.resolve_node("f2_image_edit").model_name,
            "judge_model": self.resolve_node("judge_quality").model_name,
        }

    def consume_cost(self) -> Any:
        if self.token_tracker is None:
            return None
        return self.token_tracker.to_experiment_cost()
