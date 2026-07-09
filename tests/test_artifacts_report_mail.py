from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from keeper_factory.loop.artifacts import ArtifactUploader
from keeper_factory.loop.report import build_loop_report, markdown_to_html
from keeper_factory.memory.yaml_io import dump_yaml_dict
from keeper_factory.schemas import (
    Artifacts,
    EnvInfo,
    ExperimentKind,
    ExperimentRecord,
    ExperimentStatus,
    ExecutionScores,
    JudgeSummary,
    StrategyInfo,
    Verdict,
)


def _record(
    *,
    exp_id: str,
    original: str,
    result: str,
    prompt: str,
    case_id: str = "case_001",
) -> ExperimentRecord:
    return ExperimentRecord(
        exp_id=exp_id,
        exp_sig="sig",
        loop=1,
        batch=1,
        kind=ExperimentKind.MAIN,
        case_id=case_id,
        strategy=StrategyInfo(
            p1_version="p1_v001",
            candidate_index=1,
            declared_dimension="light_shadow",
            strategy_digest="abcd",
            injected_knowledge=[],
        ),
        env=EnvInfo(
            vlm="v",
            edit_model="e",
            judge_model="j",
            p1_hash="p",
            redline_prompt_hash="r",
            quality_prompt_hash="q",
            dimension_vocab="d",
            anchor_set="a",
        ),
        artifacts=Artifacts(
            original_image_url=original,
            edit_prompt_url=prompt,
            result_image_url=result,
            result_image_sha256="0" * 64,
            upload_pending=False,
        ),
        judge_summary=JudgeSummary(
            redline_pass=True,
            verdict_vs_original=Verdict.BETTER,
            direction_score=3,
            execution_scores=ExecutionScores(
                realization=3,
                intensity=2,
                collateral_damage=3,
            ),
            failure_tags=["ok"],
        ),
        judge_result_url="https://oss.example.com/judge.json",
        status=ExperimentStatus.COMPLETED,
        created_at="2026-01-01T00:00:00Z",
    )


def test_publish_file_cleans_local_on_success(tmp_path: Path) -> None:
    from keeper_factory.oss import UploadResult

    local = tmp_path / "tmp.png"
    local.write_bytes(b"png-bytes")

    class FakeClient:
        def upload_with_fallback(self, data, oss_key, *, local_fallback_dir):
            assert data == b"png-bytes"
            return UploadResult(
                url=f"https://bucket.example.com/{oss_key}",
                oss_key=oss_key,
                sha256="ab",
                pending=False,
            )

    loaded = SimpleNamespace(
        data_root=tmp_path,
        secrets=object(),
        config=SimpleNamespace(oss=SimpleNamespace()),
    )
    uploader = ArtifactUploader.__new__(ArtifactUploader)
    uploader.loaded = loaded  # type: ignore[assignment]
    uploader.fallback_dir = tmp_path / "pending"
    uploader._client = FakeClient()  # type: ignore[assignment]
    uploader._original_url_cache = {}

    ref = uploader.publish_file(local, oss_key="experiments/x.png", cleanup=True)
    assert ref.url.startswith("https://")
    assert ref.cleaned is True
    assert not local.exists()


def test_publish_file_keeps_local_when_pending(tmp_path: Path) -> None:
    from keeper_factory.oss import UploadResult

    local = tmp_path / "tmp.png"
    local.write_bytes(b"png-bytes")

    class FakeClient:
        def upload_with_fallback(self, data, oss_key, *, local_fallback_dir):
            pending = local_fallback_dir / "x.png"
            local_fallback_dir.mkdir(parents=True, exist_ok=True)
            pending.write_bytes(data)
            return UploadResult(
                url="",
                oss_key=oss_key,
                sha256="ab",
                pending=True,
                local_path=str(pending),
            )

    uploader = ArtifactUploader.__new__(ArtifactUploader)
    uploader.loaded = SimpleNamespace(data_root=tmp_path)  # type: ignore[assignment]
    uploader.fallback_dir = tmp_path / "pending"
    uploader._client = FakeClient()  # type: ignore[assignment]
    uploader._original_url_cache = {}

    ref = uploader.publish_file(local, oss_key="experiments/x.png", cleanup=True)
    assert ref.pending is True
    assert ref.url.startswith("file://")
    assert local.exists()


def test_build_loop_report_chinese_layout(tmp_path: Path) -> None:
    case_dir = tmp_path / "goldenset" / "case_001"
    case_dir.mkdir(parents=True)
    dump_yaml_dict(
        case_dir / "target_card.yaml",
        {
            "case_id": "case_001",
            "category": "bad",
            "scene_brief": "室内走廊人像",
            "candidate_dimensions": [{"dimension": "light_shadow", "hint": "提亮人脸"}],
            "must_keep": ["身份"],
            "forbidden": ["换场景"],
            "problem_note": "脸偏暗",
        },
    )
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8), mode="RGB").save(
        case_dir / "original.png"
    )

    state = SimpleNamespace(
        loop=1,
        batch=1,
        case_id="case_001",
        category="bad",
        top_candidate_id="loop001_main_c1",
        top_recipe_id="cr_0001",
        candidates=[
            {
                "declared_dimension": "light_shadow",
                "strategy_summary": "lift subject, freeze identity",
            }
        ],
        candidate_exp_ids=["loop001_main_c1"],
        injected_knowledge=["pp_0001"],
        summary_lines=["case=case_001"],
        dnr_skipped=0,
        report_path=None,
    )
    record = _record(
        exp_id="loop001_main_c1",
        original="https://oss.example.com/original.png",
        result="https://oss.example.com/result.png",
        prompt="https://oss.example.com/prompt.txt",
    )
    body, short, score = build_loop_report(
        state=state,
        records=[record],
        validation=None,
        synthesis=None,
        loops_root=tmp_path,
        stagnation_threshold=3,
        t0_text="把照片发展成有生活感的作品。",
        data_root=tmp_path,
    )
    assert body.startswith("# 第 1 轮报告\n\n## T0 目标\n")
    assert "把照片发展成有生活感的作品。" in body
    assert "## 本轮使用的数据集样本" in body
    assert "`case_001`" in body
    assert "室内走廊人像" in body
    assert "| 字段 | 内容 |" in body
    assert "| 原图 | 结果图 |" in body
    assert (
        "| ![loop001_main_c1 原图](https://oss.example.com/original.png) "
        "| ![loop001_main_c1 结果图](https://oss.example.com/result.png) |"
    ) in body
    assert "lift subject, freeze identity" in body
    assert "实验详情（完整输入/输出）" in body
    assert short[0] == "case=case_001"
    assert score == 1  # bad + better


def test_markdown_to_html_responsive_compare_table() -> None:
    md = (
        "# 标题\n\n"
        "| 原图 | 结果图 |\n"
        "| --- | --- |\n"
        "| ![o](https://oss.example.com/a.png) | ![r](https://oss.example.com/b.png) |\n\n"
        "- item\n"
    )
    html = markdown_to_html(md)
    assert "<h1>标题</h1>" in html
    assert 'width:100%' in html
    assert 'table-layout:fixed' in html
    assert '<img src="https://oss.example.com/a.png"' in html
    assert '<img src="https://oss.example.com/b.png"' in html
    assert "<table" in html
    assert "<li>item</li>" in html
