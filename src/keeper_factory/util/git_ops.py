from __future__ import annotations

import re
import subprocess
from pathlib import Path


def is_git_dirty(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git status failed: {result.stderr.strip()}")
    return bool(result.stdout.strip())


def git_commit_all(repo_root: Path, message: str) -> bool:
    """Stage all changes and commit. Returns True if a commit was created."""
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise RuntimeError(f"git status failed: {status.stderr.strip()}")
    if not status.stdout.strip():
        return False
    add = subprocess.run(["git", "add", "-A"], cwd=repo_root, check=False, capture_output=True, text=True)
    if add.returncode != 0:
        raise RuntimeError(f"git add failed: {add.stderr.strip()}")
    commit = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        raise RuntimeError(f"git commit failed: {commit.stderr.strip()}")
    return True


_INVALID_REF = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_git_message(message: str) -> str:
    cleaned = _INVALID_REF.sub(" ", message).strip()
    return cleaned or "keeper-factory update"
