from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from keeper_factory.config import load_config
from keeper_factory.models.dry_run import FixtureRequest, FixtureResponse, FixtureStore
from keeper_factory.models.generate_json import (
    extract_json_text,
    parse_and_validate,
    schema_prompt_appendix,
)
from keeper_factory.models.hub import ModelHub
from keeper_factory.models.llm_api import ImageEditAPI, LLMApiError, is_transient_llm_error
from keeper_factory.models.token_tracker import TokenTracker
from keeper_factory.oss import OssClient


class SampleSchema(BaseModel):
    answer: str
    score: int = Field(ge=0, le=5)


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def loaded_config(project_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KF_LLM_API_KEY", "test-llm-key")
    monkeypatch.setenv("KF_OSS_AK", "test-oss-ak")
    monkeypatch.setenv("KF_OSS_SK", "test-oss-sk")
    monkeypatch.setenv("KF_MAIL_PASSWORD", "test-mail-pass")
    return load_config(project_root / "config.example.json", project_root=project_root)


def test_extract_json_text_strips_fence() -> None:
    raw = 'Here is JSON:\n```json\n{"answer": "ok", "score": 3}\n```'
    assert json.loads(extract_json_text(raw))["answer"] == "ok"


def test_schema_prompt_appendix_contains_schema() -> None:
    appendix = schema_prompt_appendix(SampleSchema)
    assert "answer" in appendix
    assert "score" in appendix


def test_parse_and_validate() -> None:
    result = parse_and_validate('{"answer": "x", "score": 2}', SampleSchema)
    assert result.answer == "x"
    assert result.score == 2


def test_is_transient_llm_error_status_codes() -> None:
    exc = LLMApiError("Chat completion API error: status=429, detail=rate limited")
    assert is_transient_llm_error(exc) is True


def test_token_tracker_aggregates_by_model() -> None:
    tracker = TokenTracker()
    tracker.record_vlm_call(
        "gpt-5.5",
        {"input_tokens": 100, "output_tokens": 20, "thinking_tokens": 5, "cache_tokens": 10},
    )
    tracker.record_vlm_call(
        "gpt-5.5",
        {"input_tokens": 50, "output_tokens": 10, "thinking_tokens": 0, "cache_tokens": 0},
    )
    cost = tracker.to_experiment_cost()
    assert cost.calls.vlm == 2
    assert len(cost.tokens) == 1
    assert cost.tokens[0].input == 150
    assert cost.tokens[0].output == 30
    assert cost.tokens[0].output_thinking == 5
    assert cost.tokens[0].input_cached == 10


def test_fixture_store_roundtrip(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    request = FixtureRequest(
        node="f5_report",
        model_name="gpt-5.5",
        system_prompt="",
        user_prompt="hello",
    )
    store.save(request, FixtureResponse(response_type="text", text='{"answer":"ok","score":1}'))
    loaded = store.require(request)
    assert loaded.text is not None
    assert "ok" in loaded.text


def test_model_hub_dry_run_text(tmp_path: Path, loaded_config) -> None:
    hub = ModelHub.from_loaded(
        loaded_config,
        dry_run=True,
        fixtures_dir=tmp_path / "fixtures",
    )
    user_prompt = "summarize"
    full_prompt = user_prompt + schema_prompt_appendix(SampleSchema)
    request = FixtureRequest(
        node="f5_report",
        model_name="gpt-5.5",
        system_prompt="",
        user_prompt=full_prompt,
    )
    FixtureStore(tmp_path / "fixtures").save(
        request,
        FixtureResponse(
            response_type="text",
            text='{"answer":"dry","score":4}',
            token_usage={"input_tokens": 1, "output_tokens": 2, "thinking_tokens": 0},
        ),
    )
    result = hub.generate_json(
        node="f5_report",
        schema=SampleSchema,
        user_prompt=user_prompt,
    )
    assert result.data.answer == "dry"
    cost = hub.consume_cost()
    assert cost.calls.vlm == 1


def test_model_hub_resolve_node_defaults(loaded_config) -> None:
    hub = ModelHub.from_loaded(loaded_config)
    resolved = hub.resolve_node("f2_image_edit")
    assert resolved.model_name == "gpt-image-2"
    assert resolved.api_kind == "edit"


def test_model_hub_edit_client_ignores_thinking_kwargs(loaded_config) -> None:
    hub = ModelHub.from_loaded(loaded_config)
    resolved = hub.resolve_node("f2_image_edit")
    client = hub._get_edit(resolved)
    assert isinstance(client, ImageEditAPI)
    assert client.image_edit_max_long_edge == 512
    assert client.image_edit_max_pixels == 512 * 512


def test_image_edit_upload_dimensions_cap_at_512() -> None:
    from keeper_factory.models.llm_api import (
        MIN_PIXELS,
        _image_edit_output_size,
        _image_edit_upload_dimensions,
    )

    w, h = _image_edit_upload_dimensions(2048, 1536, max_long_edge=512, max_pixels=512 * 512)
    assert max(w, h) <= 512
    assert w * h <= 512 * 512
    assert w % 16 == 0 and h % 16 == 0

    out_w, out_h = _image_edit_output_size(2048, 1536)
    assert out_w * out_h >= MIN_PIXELS
    assert max(out_w, out_h) >= 1024
    assert out_w % 16 == 0 and out_h % 16 == 0

    # Regression: small/square sources must not collapse to invalid 800x800.
    for src in ((512, 512), (800, 800), (640, 480), (2048, 2048)):
        ow, oh = _image_edit_output_size(*src)
        assert ow * oh >= MIN_PIXELS, (src, ow, oh)
        assert ow % 16 == 0 and oh % 16 == 0
        assert f"{ow}x{oh}" != "800x800"


def test_oss_client_builds_public_url(loaded_config) -> None:
    client = OssClient(loaded_config)
    url = client.get_public_url("keeper_factory/mvp01/test.jpg")
    assert url.startswith("https://")
    assert "test.jpg" in url
