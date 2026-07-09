from __future__ import annotations

import json
from pathlib import Path


def load_recent_loop_summaries(
    loops_root: Path,
    *,
    current_loop: int,
    context_window: int,
) -> list[str]:
    if context_window <= 0 or current_loop <= 1:
        return []

    lines: list[str] = []
    start = max(1, current_loop - context_window)
    for loop_no in range(start, current_loop):
        path = loops_root / f"loop_{loop_no:03d}.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary = payload.get("summary_lines") or []
        if not summary:
            continue
        lines.append(f"Loop {loop_no}:")
        lines.extend(f"  - {item}" for item in summary)
    return lines
