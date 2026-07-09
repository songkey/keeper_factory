from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from keeper_factory.loop.artifacts import ArtifactUploader
from keeper_factory.loop.report import (
    build_loop_report,
    mail_subject_batch,
    mail_subject_loop,
    markdown_to_html,
    report_title,
)
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
            j1_prompt_url="https://oss.example.com/j1.txt",
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
    from keeper_factory.schemas import (
        Confidence,
        KnowledgeDocument,
        KnowledgeScope,
        KnowledgeStatus,
        KnowledgeType,
        ValidationState,
    )
    from keeper_factory.loop.validation import ValidationCampaignResult, ValidationOutcome

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

    exp_dir = tmp_path / "ledger" / "experiments" / "loop_001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "loop001_main_c1_j1_prompt.txt").write_text(
        "J1_PROMPT_FOR_VLM\n", encoding="utf-8"
    )
    (exp_dir / "loop001_main_c1_edit_prompt.txt").write_text(
        "FULL_EDIT_PROMPT_BODY\nline2\n", encoding="utf-8"
    )
    (exp_dir / "loop001_val_s1_j1_prompt.txt").write_text(
        "VAL_J1_PROMPT\n", encoding="utf-8"
    )
    (exp_dir / "loop001_val_s1_edit_prompt.txt").write_text(
        "VAL_PROMPT_BODY\n", encoding="utf-8"
    )

    recipe = KnowledgeDocument(
        id="cr_0001",
        type=KnowledgeType.CASE_RECIPE,
        status=KnowledgeStatus.CANDIDATE,
        created_loop=1,
        updated_loop=1,
        scope=KnowledgeScope(dimensions=["light_shadow"], categories=[], image_class="室内"),
        confidence=Confidence.LOW,
        evidence=["loop001_main_c1"],
        case_id="case_001",
        declared_dimension="light_shadow",
        strategy_summary="提亮主体并冻结身份",
        p1_variant_ref="p1_v001",
        validation_state=ValidationState.PENDING,
        ttl_loops=5,
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
    val_record = ExperimentRecord(
        exp_id="loop001_val_s1",
        exp_sig="sigv",
        loop=1,
        batch=1,
        kind=ExperimentKind.VALIDATION,
        case_id="case_001",
        strategy=StrategyInfo(
            p1_version="p1_v001",
            candidate_index=1,
            declared_dimension="light_shadow",
            strategy_digest="abcd",
            injected_knowledge=[],
            validates_recipe="cr_0001",
        ),
        env=record.env,
        artifacts=Artifacts(
            original_image_url="https://oss.example.com/val_original.png",
            j1_prompt_url="https://oss.example.com/val_j1.txt",
            edit_prompt_url="https://oss.example.com/val_prompt.txt",
            result_image_url="https://oss.example.com/val_result.png",
            result_image_sha256="1" * 64,
            upload_pending=False,
        ),
        judge_summary=JudgeSummary(
            redline_pass=True,
            verdict_vs_original=Verdict.SAME,
            direction_score=2,
            execution_scores=ExecutionScores(
                realization=2, intensity=2, collateral_damage=3
            ),
            failure_tags=[],
        ),
        judge_result_url="https://oss.example.com/val_judge.json",
        status=ExperimentStatus.COMPLETED,
        created_at="2026-01-01T00:00:00Z",
    )
    validation = ValidationCampaignResult(
        recipe_id="cr_0001",
        outcomes=[
            ValidationOutcome(
                case_id="case_001",
                exp_id="loop001_val_s1",
                score=0,
                verdict=Verdict.SAME,
                redline_pass=True,
                original_image_url="https://oss.example.com/val_original.png",
                result_image_url="https://oss.example.com/val_result.png",
            )
        ],
        total_score=0,
        worse_count=0,
    )
    body, short, score = build_loop_report(
        state=state,
        records=[record],
        validation=validation,
        synthesis=None,
        loops_root=tmp_path,
        stagnation_threshold=3,
        t0_text="把照片发展成有生活感的作品。",
        data_root=tmp_path,
        validation_records=[val_record],
        top_recipe=recipe,
    )
    assert body.startswith("# 第 1 轮报告\n\n## T0 目标\n")
    assert "把照片发展成有生活感的作品。" in body
    assert "提亮主体并冻结身份" in body
    assert "| 序号 | 阶段 | 说明 |" in body
    assert "| 1 | F.1 |" in body
    assert "J1_PROMPT_FOR_VLM" in body
    assert "FULL_EDIT_PROMPT_BODY" in body
    assert "VAL_J1_PROMPT" in body
    assert "VAL_PROMPT_BODY" in body
    assert "| J1 提示词 |" in body
    assert "| 编辑提示词 |" in body
    assert "| 裁判 JSON | [打开](https://oss.example.com/judge.json)" in body
    assert "#### 编辑提示词（完整）" not in body
    assert "#### 裁判 JSON（完整）" not in body
    assert (
        "| ![loop001_val_s1 原图](https://oss.example.com/val_original.png) "
        "| ![loop001_val_s1 结果图](https://oss.example.com/val_result.png) |"
    ) in body
    assert "| 原图 | 结果图 |" in body
    assert short[0] == "case=case_001"
    assert score == 1  # bad + better


def test_report_and_mail_titles_include_exp_name(tmp_path: Path) -> None:
    assert report_title(loop=3, exp_name=None) == "# 第 3 轮报告"
    assert report_title(loop=3, exp_name="expA") == "# [expA] 第 3 轮报告"
    assert mail_subject_loop(loop=3, exp_name=None) == "[KF][loop 003] Report"
    assert mail_subject_loop(loop=3, exp_name="expA") == "[KF][expA][loop 003] Report"
    assert mail_subject_batch(batch=2, exp_name="expA") == (
        "[KF][expA][batch 002] pending approval"
    )

    state = SimpleNamespace(
        loop=3,
        batch=1,
        case_id="case_002",
        category="bad",
        top_candidate_id=None,
        top_recipe_id=None,
        candidates=[],
        candidate_exp_ids=[],
        injected_knowledge=[],
        summary_lines=[],
        dnr_skipped=0,
        report_path=None,
    )
    body, _, _ = build_loop_report(
        state=state,
        records=[],
        validation=None,
        synthesis=None,
        loops_root=tmp_path,
        stagnation_threshold=3,
        t0_text="t0",
        data_root=tmp_path,
        exp_name="expA",
    )
    assert body.startswith("# [expA] 第 3 轮报告\n")
    assert "| 实验名 | `expA` |" in body


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
