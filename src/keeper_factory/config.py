from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── paths ──────────────────────────────────────────────────────────────────


class PathsConfig(StrictModel):
    data_root: str = "./data"
    data_remote: str = ""


# ── loop / memory / promotion ──────────────────────────────────────────────


class LoopConfig(StrictModel):
    batch_size: int = Field(ge=1)
    candidate_num: int = Field(ge=1)
    context_window: int = Field(ge=0)
    stagnation_threshold: int = Field(ge=1)


class MemoryConfig(StrictModel):
    case_recipe_ttl: int = Field(ge=1)
    max_injection_num: int = Field(ge=0)


class PromotionConfig(StrictModel):
    min_samples: int = Field(ge=1)
    worse_rate_max: float = Field(ge=0.0, le=1.0)


# ── models ─────────────────────────────────────────────────────────────────


class ModelsApiConfig(StrictModel):
    request_url: str
    api_key_env: str
    timeout_seconds: int = Field(ge=1)
    image_edit_timeout_seconds: int = Field(ge=1)


class ModelsDefaultsConfig(StrictModel):
    vlm: str
    edit: str


class NodeConfig(StrictModel):
    model_name: str
    max_long_edge: int | None = None
    thinking: bool | None = None
    reasoning_effort: str | None = None
    max_tokens: int | None = None


NodeName = Literal[
    "f1_candidate",
    "f2_edit_prompt",
    "f2_image_edit",
    "judge_redline",
    "judge_quality",
    "judge_pairwise",
    "f4_synthesis",
    "f4_refine",
    "f5_report",
]


class ModelsNodesConfig(StrictModel):
    f1_candidate: NodeConfig
    f2_edit_prompt: NodeConfig
    f2_image_edit: NodeConfig
    judge_redline: NodeConfig
    judge_quality: NodeConfig
    judge_pairwise: NodeConfig
    f4_synthesis: NodeConfig
    f4_refine: NodeConfig
    f5_report: NodeConfig


class ModelsConfig(StrictModel):
    api: ModelsApiConfig
    defaults: ModelsDefaultsConfig
    nodes: ModelsNodesConfig


# ── oss / mail / logging ───────────────────────────────────────────────────


class OssConfig(StrictModel):
    endpoint: str
    bucket: str
    prefix: str
    access_key_env: str
    secret_key_env: str


class MailConfig(StrictModel):
    smtp_host: str
    smtp_port: int = Field(ge=1, le=65535)
    imap_host: str
    imap_port: int = Field(ge=1, le=65535)
    username: str
    password_env: str
    from_: str = Field(alias="from")
    approvers: list[str] = Field(min_length=1)
    poll_interval_seconds: int = Field(ge=1)
    reminder_hours: int = Field(ge=1)

    @field_validator("approvers")
    @classmethod
    def non_empty_approvers(cls, v: list[str]) -> list[str]:
        if not all(a.strip() for a in v):
            raise ValueError("approvers must be non-empty strings")
        return v


class LoggingConfig(StrictModel):
    level: str = "INFO"
    file: str = "ledger/logs/kf.log"


# ── root config ────────────────────────────────────────────────────────────


class AppConfig(StrictModel):
    paths: PathsConfig
    loop: LoopConfig
    memory: MemoryConfig
    promotion: PromotionConfig
    models: ModelsConfig
    oss: OssConfig
    mail: MailConfig
    logging: LoggingConfig


@dataclass(frozen=True)
class ResolvedSecrets:
    api_key: str
    oss_access_key: str
    oss_secret_key: str
    mail_password: str


@dataclass(frozen=True)
class LoadedConfig:
    config: AppConfig
    secrets: ResolvedSecrets | None
    config_hash: str
    prompts_hash: str
    project_root: Path
    data_root: Path
    prompts_dir: Path
    log_file: Path


def _resolve_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return value


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_config_hash(config: AppConfig) -> str:
    payload = _canonical_json(config.model_dump(mode="json", by_alias=True))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_prompts_hash(prompts_dir: Path) -> str:
    if not prompts_dir.is_dir():
        raise FileNotFoundError(f"Prompts directory not found: {prompts_dir}")
    hasher = hashlib.sha256()
    for path in sorted(prompts_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(prompts_dir).as_posix()
            hasher.update(rel.encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(path.read_bytes())
            hasher.update(b"\0")
    return hasher.hexdigest()


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError(
        "Could not locate project root (no pyproject.toml found in cwd or parents)"
    )


def load_config(
    config_path: Path | None = None,
    *,
    project_root: Path | None = None,
    resolve_secrets: bool = True,
) -> LoadedConfig:
    root = project_root or find_project_root(
        config_path.parent if config_path else None
    )
    path = config_path or (root / "config.json")
    if not path.is_file():
        example = root / "config.example.json"
        hint = f"; copy {example.name} to config.json" if example.is_file() else ""
        raise FileNotFoundError(f"Config file not found: {path}{hint}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    config = AppConfig.model_validate(raw)

    data_root = (root / config.paths.data_root).resolve()
    prompts_dir = root / "prompts"
    log_file = data_root / config.logging.file

    secrets: ResolvedSecrets | None = None
    if resolve_secrets:
        secrets = ResolvedSecrets(
            api_key=_resolve_env(config.models.api.api_key_env),
            oss_access_key=_resolve_env(config.oss.access_key_env),
            oss_secret_key=_resolve_env(config.oss.secret_key_env),
            mail_password=_resolve_env(config.mail.password_env),
        )

    return LoadedConfig(
        config=config,
        secrets=secrets,
        config_hash=compute_config_hash(config),
        prompts_hash=compute_prompts_hash(prompts_dir),
        project_root=root,
        data_root=data_root,
        prompts_dir=prompts_dir,
        log_file=log_file,
    )
