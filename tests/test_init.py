from __future__ import annotations

from pathlib import Path

from keeper_factory.config import AppConfig
from keeper_factory.init_data import init_data_repo, scaffold_data_dirs, seed_demo_goldenset


def test_scaffold_data_dirs(tmp_path: Path) -> None:
    created = scaffold_data_dirs(tmp_path)
    assert (tmp_path / "goldenset").is_dir()
    assert (tmp_path / "memory/case_recipes").is_dir()
    assert (tmp_path / "ledger/logs").is_dir()
    assert (tmp_path / ".gitignore").is_file()
    assert len(created) >= 12


def test_init_data_repo_idempotent(tmp_path: Path) -> None:
    config = AppConfig.model_validate(
        {
            "paths": {"data_root": str(tmp_path), "data_remote": ""},
            "loop": {
                "batch_size": 5,
                "candidate_num": 3,
                "context_window": 3,
                "stagnation_threshold": 3,
            },
            "memory": {"case_recipe_ttl": 5, "max_injection_num": 3},
            "promotion": {"min_samples": 3, "worse_rate_max": 0.25},
            "models": {
                "api": {
                    "request_url": "https://api.example.com",
                    "api_key_env": "KF_LLM_API_KEY",
                    "timeout_seconds": 180,
                    "image_edit_timeout_seconds": 240,
                },
                "defaults": {"vlm": "gpt-5.5", "edit": "gpt-image-2"},
                "nodes": {
                    "f1_candidate": {"model_name": "gpt-5.5", "max_long_edge": 768},
                    "f2_edit_prompt": {"model_name": "gpt-5.5", "max_long_edge": 768},
                    "f2_image_edit": {"model_name": "gpt-image-2"},
                    "judge_redline": {
                        "model_name": "gpt-5.5",
                        "max_long_edge": 1024,
                        "thinking": True,
                    },
                    "judge_quality": {
                        "model_name": "gpt-5.5",
                        "max_long_edge": 1024,
                        "thinking": True,
                    },
                    "judge_pairwise": {
                        "model_name": "gpt-5.5",
                        "max_long_edge": 1024,
                        "thinking": True,
                    },
                    "f4_synthesis": {"model_name": "gpt-5.5", "thinking": True},
                    "f4_refine": {"model_name": "gpt-5.5", "thinking": True},
                    "f5_report": {"model_name": "gpt-5.5", "thinking": False},
                },
            },
            "oss": {
                "endpoint": "https://oss.example.com",
                "bucket": "b",
                "prefix": "p",
                "access_key_env": "KF_OSS_AK",
                "secret_key_env": "KF_OSS_SK",
            },
            "mail": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 465,
                "imap_host": "imap.example.com",
                "imap_port": 993,
                "username": "u",
                "password_env": "KF_MAIL_PASSWORD",
                "from": "f@example.com",
                "approvers": ["a@example.com"],
                "poll_interval_seconds": 300,
                "reminder_hours": 1,
            },
            "logging": {"level": "INFO", "file": "ledger/logs/kf.log"},
        }
    )
    msg1 = init_data_repo(config, tmp_path)
    msg2 = init_data_repo(config, tmp_path)
    assert (tmp_path / ".git").is_dir()
    assert "already present" in msg2 or "nothing to commit" in msg2
    assert msg1  # non-empty message


def test_seed_demo_goldenset(tmp_path: Path) -> None:
    created = seed_demo_goldenset(tmp_path)
    assert created
    assert (tmp_path / "goldenset/case_001/target_card.yaml").is_file()
    assert (tmp_path / "goldenset/case_001/original.png").is_file()
    assert (tmp_path / "goldenset/anchors/anchor_v0.yaml").is_file()
