from __future__ import annotations

from io import BytesIO
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from keeper_factory.config import AppConfig, LoadedConfig
from keeper_factory.memory.yaml_io import dump_yaml_dict

DATA_GITIGNORE = """# runtime logs (CF3)
ledger/logs/
*.log

.DS_Store
"""

DATA_DIRS = [
    "goldenset",
    "goldenset/anchors",
    "memory/case_recipes",
    "memory/pattern_patches",
    "memory/failure_notes",
    "memory/capability_notes",
    "ledger/experiments",
    "ledger/loops",
    "ledger/batches",
    "ledger/p1_versions",
    "ledger/reports",
    "ledger/logs",
]


def scaffold_data_dirs(data_root: Path) -> list[Path]:
    created: list[Path] = []
    for rel in DATA_DIRS:
        path = data_root / rel
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    gitignore = data_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(DATA_GITIGNORE, encoding="utf-8")
        created.append(gitignore)
    return created


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def init_data_repo(config: AppConfig, data_root: Path) -> str:
    data_root.mkdir(parents=True, exist_ok=True)
    created = scaffold_data_dirs(data_root)

    git_dir = data_root / ".git"
    if not git_dir.exists():
        result = _run_git(["init"], cwd=data_root)
        if result.returncode != 0:
            raise RuntimeError(f"git init failed: {result.stderr.strip()}")

    remote = config.paths.data_remote.strip()
    if remote:
        remotes = _run_git(["remote"], cwd=data_root)
        if remotes.returncode == 0 and "origin" not in remotes.stdout.split():
            result = _run_git(["remote", "add", "origin", remote], cwd=data_root)
            if result.returncode != 0:
                raise RuntimeError(f"git remote add failed: {result.stderr.strip()}")

    status = _run_git(["status", "--porcelain"], cwd=data_root)
    if status.returncode != 0:
        raise RuntimeError(f"git status failed: {status.stderr.strip()}")

    committed = False
    if status.stdout.strip():
        _run_git(["add", "-A"], cwd=data_root)
        result = _run_git(["commit", "-m", "kf init: scaffold data repository"], cwd=data_root)
        if result.returncode != 0:
            raise RuntimeError(f"git commit failed: {result.stderr.strip()}")
        committed = True

    if created:
        summary = f"created {len(created)} path(s)"
    else:
        summary = "directories already present"
    if committed:
        return f"{summary}; initial commit recorded"
    return f"{summary}; nothing to commit"


def init_from_loaded(loaded: LoadedConfig) -> str:
    return init_data_repo(loaded.config, loaded.data_root)


def seed_demo_goldenset(data_root: Path) -> list[Path]:
    """Create a minimal demo case + anchor for dry-run end-to-end."""
    created: list[Path] = []
    case_dir = data_root / "goldenset" / "case_001"
    case_dir.mkdir(parents=True, exist_ok=True)
    if not case_dir.exists():
        created.append(case_dir)

    target_card_path = case_dir / "target_card.yaml"
    if not target_card_path.exists():
        dump_yaml_dict(
            target_card_path,
            {
                "case_id": "case_001",
                "category": "bad",
                "demo": True,
                "scene_brief": "sunset portrait by the sea",
                "candidate_dimensions": [
                    {
                        "dimension": "light_shadow",
                        "hint": "lift subject exposure while preserving sunset highlights",
                    }
                ],
                "must_keep": ["identity", "sea-sky transition"],
                "forbidden": ["add objects"],
                "problem_note": "subject underexposed and sky highlights clipped",
            },
        )
        created.append(target_card_path)

    original_path = case_dir / "original.png"
    if not original_path.exists():
        # simple gradient-like synthetic image
        h, w = 256, 256
        yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        xx = np.linspace(0, 1, w, dtype=np.float32)[None, :]
        r = np.broadcast_to((80 + 120 * xx).clip(0, 255), (h, w))
        g = np.broadcast_to((70 + 90 * (1 - yy)).clip(0, 255), (h, w))
        b = np.broadcast_to((110 + 80 * yy).clip(0, 255), (h, w))
        image = np.stack([r, g, b], axis=2).astype(np.uint8)
        Image.fromarray(image, mode="RGB").save(original_path)
        created.append(original_path)

    anchor_dir = data_root / "goldenset" / "anchors"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = anchor_dir / "anchor_v0.yaml"
    if not anchor_path.exists():
        dump_yaml_dict(
            anchor_path,
            {
                "version": "anchor_v0",
                "examples": [
                    {
                        "case_id": "case_001",
                        "expected_verdict": "better",
                        "violation_types": [],
                        "notes": "subject brighter, scene still realistic",
                    }
                ],
            },
        )
        created.append(anchor_path)

    return created


def seed_demo_from_loaded(loaded: LoadedConfig) -> str:
    created = seed_demo_goldenset(loaded.data_root)
    if not created:
        return "demo goldenset already exists"
    return f"seeded demo assets: {len(created)} file(s)"
