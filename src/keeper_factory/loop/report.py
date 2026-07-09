from __future__ import annotations

import html
import json
import re
from pathlib import Path

from keeper_factory.goldenset import load_target_card
from keeper_factory.loop.synthesis import SynthesisResult
from keeper_factory.loop.validation import ValidationCampaignResult
from keeper_factory.schemas import ExperimentRecord, TargetCard


_CATEGORY_ZH = {
    "bad": "差样本",
    "good": "好样本",
    "redline": "红线样本",
}

_VERDICT_ZH = {
    "better": "更好",
    "same": "持平",
    "worse": "更差",
}

_KIND_ZH = {
    "main": "主实验",
    "validation": "验证",
}


def _stagnation_flag(loops_root: Path, *, current_loop: int, threshold: int) -> bool:
    if threshold <= 0 or current_loop < threshold:
        return False
    recent_scores: list[int] = []
    for loop_no in range(current_loop - threshold + 1, current_loop + 1):
        path = loops_root / f"loop_{loop_no:03d}.json"
        if not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        score = payload.get("main_score")
        if score is None:
            return False
        recent_scores.append(int(score))
    if len(recent_scores) < threshold:
        return False
    return max(recent_scores) == min(recent_scores)


def _md_link(label: str, url: str | None) -> str:
    if not url:
        return "（缺失）"
    return f"[{label}]({url})"


def _md_image(alt: str, url: str | None) -> str:
    if not url:
        return f"_{alt}：缺失_"
    if url.startswith("file://"):
        return f"{alt}：`{url}`"
    return f"![{alt}]({url})"


def _kv_table(rows: list[tuple[str, str]]) -> list[str]:
    """Render key/value pairs as a two-column markdown table."""
    if not rows:
        return ["| 字段 | 内容 |", "| --- | --- |", "| （无） | （无） |", ""]
    lines = ["| 字段 | 内容 |", "| --- | --- |"]
    for key, value in rows:
        cell = str(value).replace("\n", "<br>").replace("|", "\\|")
        lines.append(f"| {key} | {cell} |")
    lines.append("")
    return lines


def _category_zh(value: str | None) -> str:
    if not value:
        return "（未知）"
    return _CATEGORY_ZH.get(value, value)


def _verdict_zh(value: str | None) -> str:
    if not value:
        return "-"
    return _VERDICT_ZH.get(value, value)


def _kind_zh(value: str | None) -> str:
    if not value:
        return "-"
    return _KIND_ZH.get(value, value)


def _md_compare_table(
    *,
    exp_id: str,
    original_url: str | None,
    result_url: str | None,
) -> list[str]:
    """Side-by-side 原图 | 结果图；HTML 侧按页面宽度自适应。"""
    return [
        "| 原图 | 结果图 |",
        "| --- | --- |",
        (
            f"| {_md_image(f'{exp_id} 原图', original_url)} "
            f"| {_md_image(f'{exp_id} 结果图', result_url)} |"
        ),
        "",
    ]


def _format_target_card_cell(
    card: TargetCard,
    *,
    original_url: str | None = None,
    role: str | None = None,
) -> str:
    parts: list[str] = []
    if original_url and original_url.startswith("http"):
        parts.append(_md_image(f"{card.case_id} 原图", original_url))
    if role:
        parts.append(f"**用途** {role}")
    parts.append(f"**类别** {_category_zh(card.category.value)} (`{card.category.value}`)")
    parts.append(f"**场景** {card.scene_brief}")
    dims = "；".join(
        f"`{item.dimension}`" + (f" — {item.hint}" if item.hint else "")
        for item in card.candidate_dimensions
    )
    if dims:
        parts.append(f"**候选维度** {dims}")
    if card.problem_note:
        parts.append(f"**问题** {card.problem_note}")
    if card.established_note:
        parts.append(f"**已成立点** {card.established_note}")
    if card.trap_note:
        parts.append(f"**陷阱** {card.trap_note}")
    if card.must_keep:
        parts.append("**必须保留** " + "；".join(card.must_keep))
    if card.forbidden:
        parts.append("**禁止** " + "；".join(card.forbidden))
    return "<br>".join(parts)


def _dataset_showcase_table(
    *,
    data_root: Path | None,
    case_roles: list[tuple[str, str]],
    original_urls: dict[str, str | None],
    columns: int = 2,
) -> list[str]:
    if not case_roles or data_root is None:
        return ["（本轮无数据集样本）", ""]

    # Preserve order; merge roles when the same case appears twice.
    ordered: list[tuple[str, str]] = []
    index_by_case: dict[str, int] = {}
    for case_id, role in case_roles:
        if case_id in index_by_case:
            idx = index_by_case[case_id]
            existing_role = ordered[idx][1]
            if role not in existing_role:
                ordered[idx] = (case_id, f"{existing_role} / {role}")
            continue
        index_by_case[case_id] = len(ordered)
        ordered.append((case_id, role))

    lines: list[str] = []
    for start in range(0, len(ordered), columns):
        chunk = ordered[start : start + columns]
        headers = [case_id for case_id, _ in chunk]
        while len(headers) < columns:
            headers.append(" ")
        lines.append("| " + " | ".join(f"`{h}`" if h.strip() else " " for h in headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        cells: list[str] = []
        for case_id, role in chunk:
            try:
                card = load_target_card(data_root, case_id)
                cells.append(
                    _format_target_card_cell(
                        card,
                        original_url=original_urls.get(case_id),
                        role=role,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                cells.append(f"**用途** {role}<br>加载 Target Card 失败：{exc}")
        while len(cells) < columns:
            cells.append(" ")
        lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def _candidate_lookup(state) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for idx, candidate in enumerate(getattr(state, "candidates", []) or [], start=1):
        if not isinstance(candidate, dict):
            continue
        exp_id = None
        ids = getattr(state, "candidate_exp_ids", None) or []
        if idx - 1 < len(ids):
            exp_id = ids[idx - 1]
        if exp_id:
            out[str(exp_id)] = candidate
    return out


def _format_experiment_section(
    record: ExperimentRecord,
    *,
    strategy_summary: str | None = None,
) -> list[str]:
    summary = record.judge_summary
    arts = record.artifacts
    rows: list[tuple[str, str]] = [
        ("样本", f"`{record.case_id}`"),
        ("类型", f"{_kind_zh(record.kind.value)} (`{record.kind.value}`)"),
        ("维度", f"`{record.strategy.declared_dimension}`"),
        ("P.1", f"`{record.strategy.p1_version}`"),
        ("注入知识", ", ".join(f"`{x}`" for x in record.strategy.injected_knowledge) or "（无）"),
    ]
    if strategy_summary:
        rows.append(("策略", strategy_summary))
    if summary is not None:
        tags = ", ".join(summary.failure_tags) or "（无）"
        exec_scores = summary.execution_scores
        rows.extend(
            [
                (
                    "裁决",
                    f"**{_verdict_zh(summary.verdict_vs_original.value)}** "
                    f"(`{summary.verdict_vs_original.value}`)",
                ),
                ("红线", "通过" if summary.redline_pass else "未通过"),
                ("方向分", str(summary.direction_score)),
                (
                    "执行分",
                    (
                        f"实现={exec_scores.realization} / "
                        f"强度={exec_scores.intensity} / "
                        f"附带损伤={exec_scores.collateral_damage}"
                    ),
                ),
                ("失败标签", tags),
            ]
        )
    rows.extend(
        [
            ("编辑提示词", _md_link("打开", arts.edit_prompt_url)),
            ("裁判 JSON", _md_link("打开", record.judge_result_url)),
            ("上传待重试", "是" if arts.upload_pending else "否"),
        ]
    )
    return [
        f"### {record.exp_id}",
        "",
        *_kv_table(rows),
        *_md_compare_table(
            exp_id=record.exp_id,
            original_url=arts.original_image_url,
            result_url=arts.result_image_url,
        ),
    ]


def build_loop_report(
    *,
    state,
    records: list[ExperimentRecord],
    validation: ValidationCampaignResult | None,
    synthesis: SynthesisResult | None,
    loops_root: Path,
    stagnation_threshold: int,
    dnr_skipped: int = 0,
    validation_records: list[ExperimentRecord] | None = None,
    mail_status: str | None = None,
    t0_text: str | None = None,
    data_root: Path | None = None,
) -> tuple[str, list[str], int | None]:
    candidates = _candidate_lookup(state)
    all_records = list(records) + list(validation_records or [])
    by_id = {item.exp_id: item for item in all_records}

    matrix_lines = [
        "| 实验 ID | 类型 | 裁决 | 红线 | 方向 | 执行分 | 标签 |",
        "|---|---|---|---|---|---|---|",
    ]
    verdict_counts: dict[str, int] = {}
    main_score: int | None = None

    for record in records:
        summary = record.judge_summary
        if summary is None:
            continue
        verdict = summary.verdict_vs_original.value
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        exec_s = summary.execution_scores
        tags = ",".join(summary.failure_tags) or "-"
        matrix_lines.append(
            f"| `{record.exp_id}` | {_kind_zh(record.kind.value)} | "
            f"{_verdict_zh(verdict)} | "
            f"{'通过' if summary.redline_pass else '未通过'} | {summary.direction_score} | "
            f"{exec_s.realization}/{exec_s.intensity}/{exec_s.collateral_damage} | {tags} |"
        )
        if record.exp_id == state.top_candidate_id and state.category:
            from keeper_factory.judge.scoring import category_validation_score
            from keeper_factory.schemas import CaseCategory, Verdict as V

            main_score = category_validation_score(
                category=CaseCategory(state.category),
                redline_pass=summary.redline_pass,
                verdict_vs_original=V(verdict),
            )

    knowledge_rows: list[tuple[str, str]] = []
    if synthesis:
        if synthesis.promoted_ids:
            knowledge_rows.append(
                ("晋升 Pattern Patch", ", ".join(f"`{x}`" for x in synthesis.promoted_ids))
            )
        if synthesis.failure_note_ids:
            knowledge_rows.append(
                ("新增 Failure Note", ", ".join(f"`{x}`" for x in synthesis.failure_note_ids))
            )
        if synthesis.discarded_recipe_ids:
            knowledge_rows.append(
                ("废弃 Case Recipe", ", ".join(f"`{x}`" for x in synthesis.discarded_recipe_ids))
            )
    if not knowledge_rows:
        knowledge_rows.append(("变更", "无"))

    stagnation = _stagnation_flag(
        loops_root,
        current_loop=state.loop,
        threshold=stagnation_threshold,
    )

    hypothesis = (
        f"第 {state.loop} 轮围绕 `{state.case_id}`（{_category_zh(state.category)}）"
        f"探索 {len(state.candidates)} 个候选策略。"
    )
    next_plan = "继续按类别轮转采样。"
    if stagnation:
        next_plan = "停滞：考虑策略级 P.1 重写，并安排人工复核。"
    if state.category == "good":
        next_plan = "好样本保护：优先做回归检查。"

    short_summary = list(state.summary_lines)
    if dnr_skipped:
        short_summary.append(f"dnr_skipped={dnr_skipped}")
    if main_score is not None:
        short_summary.append(f"main_score={main_score}")
    if validation:
        short_summary.append(f"validation_score={validation.total_score}")
    if synthesis and synthesis.promoted_ids:
        short_summary.append(f"promoted={','.join(synthesis.promoted_ids)}")
    if mail_status:
        short_summary.append(mail_status)

    flow_rows = [
        ("F.1", "采样样本 + 注入记忆 + 渲染 P.1"),
        ("F.2", "生成编辑提示词 + 结果图（上传 OSS）"),
        ("F.3", "裁判候选 + 写入 Case Recipe"),
        ("F.4a/b/c", "验证 / 归纳 / P.1 精炼（按需）"),
        ("F.5", "生成报告 + 发送知会邮件"),
    ]

    meta_rows = [
        ("批次", str(state.batch)),
        ("主样本", f"`{state.case_id}`"),
        ("类别", f"{_category_zh(state.category)} (`{state.category}`)"),
        ("最优候选", f"`{state.top_candidate_id}`" if state.top_candidate_id else "（无）"),
        ("最优配方", f"`{state.top_recipe_id}`" if state.top_recipe_id else "（无）"),
        (
            "报告路径",
            f"`{getattr(state, 'report_path', None) or f'ledger/reports/loop_{state.loop:03d}.md'}`",
        ),
    ]

    case_roles: list[tuple[str, str]] = []
    original_urls: dict[str, str | None] = {}
    if state.case_id:
        case_roles.append((state.case_id, "主实验（F.1–F.3）"))
    for record in records:
        if record.artifacts.original_image_url:
            original_urls.setdefault(record.case_id, record.artifacts.original_image_url)
    if validation:
        for item in validation.outcomes:
            case_roles.append((item.case_id, f"验证 `{item.exp_id}`"))
            if item.original_image_url:
                original_urls.setdefault(item.case_id, item.original_image_url)
    for record in validation_records or []:
        if record.artifacts.original_image_url:
            original_urls.setdefault(record.case_id, record.artifacts.original_image_url)

    candidate_rows: list[tuple[str, str]] = [
        ("注入知识", ", ".join(f"`{x}`" for x in state.injected_knowledge) or "（无）"),
        ("候选数量", str(len(state.candidates or []))),
    ]
    for idx, candidate in enumerate(state.candidates or [], start=1):
        if not isinstance(candidate, dict):
            continue
        exp_id = ""
        ids = getattr(state, "candidate_exp_ids", None) or []
        if idx - 1 < len(ids):
            exp_id = str(ids[idx - 1])
        label = f"候选 {idx}" + (f" → `{exp_id}`" if exp_id else "")
        candidate_rows.append(
            (
                label,
                (
                    f"**维度** `{candidate.get('declared_dimension')}`<br>"
                    f"**策略** {candidate.get('strategy_summary') or '（空）'}"
                ),
            )
        )

    experiment_sections: list[str] = []
    for record in records:
        strategy_summary = None
        cand = candidates.get(record.exp_id)
        if cand:
            strategy_summary = str(cand.get("strategy_summary") or "") or None
        experiment_sections.extend(
            _format_experiment_section(record, strategy_summary=strategy_summary)
        )

    validation_sections: list[str] = []
    if validation and validation.outcomes:
        validation_sections.extend(
            [
                "## 验证战役（F.4a）",
                "",
                *_kv_table(
                    [
                        ("配方", f"`{validation.recipe_id}`"),
                        ("总分", str(validation.total_score)),
                        ("变差次数", str(validation.worse_count)),
                    ]
                ),
                "| 实验 ID | 样本 | 分数 | 裁决 | 原图 | 结果图 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for item in validation.outcomes:
            record = by_id.get(item.exp_id)
            original_url = item.original_image_url or (
                record.artifacts.original_image_url if record else None
            )
            result_url = item.result_image_url or (
                record.artifacts.result_image_url if record else None
            )
            validation_sections.append(
                f"| `{item.exp_id}` | `{item.case_id}` | {item.score} | "
                f"{_verdict_zh(item.verdict.value if item.verdict else None)} | "
                f"{_md_link('图', original_url)} | {_md_link('图', result_url)} |"
            )
        validation_sections.append("")
        for item in validation.outcomes:
            record = by_id.get(item.exp_id)
            if record is not None:
                validation_sections.extend(_format_experiment_section(record))
            else:
                validation_sections.extend(
                    [
                        f"### {item.exp_id}（验证）",
                        "",
                        *_md_compare_table(
                            exp_id=item.exp_id,
                            original_url=item.original_image_url,
                            result_url=item.result_image_url,
                        ),
                    ]
                )

    t0_block = (t0_text or "").strip() or "（未配置 `prompts/t0.txt`）"
    distribution_rows = [
        (_verdict_zh(key) + f" (`{key}`)", str(count))
        for key, count in sorted(verdict_counts.items())
    ] or [("结果", "无")]

    lines = [
        f"# 第 {state.loop} 轮报告",
        "",
        "## T0 目标",
        "",
        t0_block,
        "",
        "## 本轮概览",
        "",
        *_kv_table(meta_rows),
        "## 本轮使用的数据集样本",
        "",
        *_dataset_showcase_table(
            data_root=data_root,
            case_roles=case_roles,
            original_urls=original_urls,
        ),
        "## 本轮流程",
        "",
        *_kv_table(flow_rows),
        "## 假设",
        "",
        hypothesis,
        "",
        "## 输入与候选",
        "",
        *_kv_table(candidate_rows),
        "## 实验矩阵",
        "",
        *matrix_lines,
        "",
        "## 实验详情（完整输入/输出）",
        "",
        *experiment_sections,
        *validation_sections,
        "## 结果分布",
        "",
        *_kv_table(distribution_rows),
        "## 知识变更",
        "",
        *_kv_table(knowledge_rows),
        "## 下一轮计划",
        "",
        next_plan,
        "",
        "## 停滞检查",
        "",
        *_kv_table([("是否停滞", "是" if stagnation else "否")]),
        "## 短摘要",
        "",
        *_kv_table([(f"项 {idx}", item) for idx, item in enumerate(short_summary, start=1)]),
    ]
    if mail_status:
        lines.extend(["## 邮件发送", "", *_kv_table([("状态", mail_status)])])
    return "\n".join(lines) + "\n", short_summary, main_score


_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((https?://[^)]+)\)")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_CODE_RE = re.compile(r"`([^`]+)`")


def markdown_to_html(markdown_text: str) -> str:
    """Minimal markdown → HTML for mail clients (headings, lists, tables, images, code)."""
    lines = markdown_text.splitlines()
    parts: list[str] = [
        "<html><body style=\"font-family: -apple-system, BlinkMacSystemFont, "
        "'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif; "
        "line-height:1.5; color:#222; max-width:960px; margin:0 auto; padding:12px;\">"
    ]
    in_ul = False
    in_table = False
    in_code = False
    code_buf: list[str] = []
    table_col_count = 0

    def close_ul() -> None:
        nonlocal in_ul
        if in_ul:
            parts.append("</ul>")
            in_ul = False

    def close_table() -> None:
        nonlocal in_table, table_col_count
        if in_table:
            parts.append("</table>")
            in_table = False
            table_col_count = 0

    def inline(text: str) -> str:
        escaped = html.escape(text)
        escaped = _MD_BOLD_RE.sub(r"<strong>\1</strong>", escaped)
        escaped = _MD_CODE_RE.sub(r"<code>\1</code>", escaped)
        return escaped.replace("&lt;br&gt;", "<br>").replace("&lt;br/&gt;", "<br>")

    def inline_with_media(text: str) -> str:
        chunks: list[str] = []
        pos = 0
        pattern = re.compile(
            r"!\[([^\]]*)\]\((https?://[^)]+)\)|\[([^\]]+)\]\((https?://[^)]+)\)"
        )
        for match in pattern.finditer(text):
            chunks.append(inline(text[pos : match.start()]))
            if match.group(1) is not None:
                alt = html.escape(match.group(1))
                url = html.escape(match.group(2), quote=True)
                chunks.append(
                    f'<img src="{url}" alt="{alt}" '
                    f'style="display:block;max-width:100%;width:100%;height:auto;'
                    f'border:1px solid #ddd;"/>'
                )
            else:
                label = html.escape(match.group(3))
                url = html.escape(match.group(4), quote=True)
                chunks.append(f'<a href="{url}">{label}</a>')
            pos = match.end()
        chunks.append(inline(text[pos:]))
        return "".join(chunks)

    for raw in lines:
        if in_code:
            if raw.strip().startswith("```"):
                parts.append(
                    "<pre style=\"background:#f6f8fa;padding:10px;overflow:auto;\">"
                    f"{html.escape(chr(10).join(code_buf))}</pre>"
                )
                in_code = False
                code_buf = []
            else:
                code_buf.append(raw)
            continue

        if raw.strip().startswith("```"):
            close_ul()
            close_table()
            in_code = True
            code_buf = []
            continue

        if not raw.strip():
            close_ul()
            close_table()
            continue

        heading = _MD_HEADING_RE.match(raw)
        if heading:
            close_ul()
            close_table()
            level = len(heading.group(1))
            parts.append(f"<h{level}>{inline_with_media(heading.group(2))}</h{level}>")
            continue

        if raw.lstrip().startswith("|") and "|" in raw.strip()[1:]:
            cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
            if all(set(cell) <= {"-", ":"} and cell for cell in cells):
                continue
            if not in_table:
                close_ul()
                table_col_count = max(1, len(cells))
                parts.append(
                    "<table style=\"border-collapse:collapse;margin:10px 0;width:100%;"
                    "table-layout:fixed;\" border=\"1\" cellpadding=\"8\" cellspacing=\"0\">"
                )
                in_table = True
                width = f"{100 // table_col_count}%"
                parts.append(
                    "<tr>"
                    + "".join(
                        f'<th style="width:{width};vertical-align:top;word-break:break-word;">'
                        f"{inline_with_media(cell)}</th>"
                        for cell in cells
                    )
                    + "</tr>"
                )
            else:
                width = f"{100 // max(table_col_count, len(cells))}%"
                parts.append(
                    "<tr>"
                    + "".join(
                        f'<td style="width:{width};vertical-align:top;word-break:break-word;">'
                        f"{inline_with_media(cell)}</td>"
                        for cell in cells
                    )
                    + "</tr>"
                )
            continue

        if raw.lstrip().startswith(("- ", "* ")):
            close_table()
            if not in_ul:
                parts.append("<ul>")
                in_ul = True
            item = raw.lstrip()[2:]
            parts.append(f"<li>{inline_with_media(item)}</li>")
            continue

        close_ul()
        close_table()
        parts.append(f"<p>{inline_with_media(raw)}</p>")

    close_ul()
    close_table()
    if in_code:
        parts.append(f"<pre>{html.escape(chr(10).join(code_buf))}</pre>")
    parts.append("</body></html>")
    return "\n".join(parts)


def extract_image_urls(markdown_text: str) -> list[str]:
    return [match.group(2) for match in _MD_IMAGE_RE.finditer(markdown_text)]
