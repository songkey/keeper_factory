from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from keeper_factory.config import LoadedConfig
from keeper_factory.goldenset.loader import case_dir
from keeper_factory.oss import OssClient, OssUploadError
from keeper_factory.util.hashing import sha256_hex


@dataclass(frozen=True)
class ArtifactRef:
    url: str
    sha256: str | None = None
    pending: bool = False
    cleaned: bool = False


class ArtifactUploader:
    """Upload experiment artifacts to OSS, then drop local temp copies when safe."""

    def __init__(
        self,
        loaded: LoadedConfig,
        *,
        ledger_root: Path | None = None,
        enabled: bool = True,
    ) -> None:
        self.loaded = loaded
        base = ledger_root or (loaded.data_root / "ledger")
        self.fallback_dir = base / "artifacts_pending"
        self._client: OssClient | None = None
        self._original_url_cache: dict[str, str] = {}
        if enabled and loaded.secrets is not None:
            try:
                self._client = OssClient(loaded)
            except Exception:
                self._client = None

    @property
    def oss_enabled(self) -> bool:
        return self._client is not None

    def publish_file(
        self,
        local_path: Path,
        *,
        oss_key: str,
        cleanup: bool = True,
    ) -> ArtifactRef:
        """Upload bytes from ``local_path``; delete the local file only on HTTPS success."""
        data = local_path.read_bytes()
        digest = sha256_hex(data)
        if self._client is None:
            return ArtifactRef(url=f"file://{local_path.resolve()}", sha256=digest, pending=False)

        try:
            result = self._client.upload_with_fallback(
                data,
                oss_key,
                local_fallback_dir=self.fallback_dir,
            )
        except OssUploadError:
            return ArtifactRef(url=f"file://{local_path.resolve()}", sha256=digest, pending=True)

        if result.pending or not result.url:
            fallback = result.local_path or str(local_path.resolve())
            return ArtifactRef(
                url=f"file://{Path(fallback).resolve()}",
                sha256=result.sha256 or digest,
                pending=True,
            )

        cleaned = False
        if cleanup and local_path.is_file() and result.url.startswith("https://"):
            try:
                local_path.unlink()
                cleaned = True
            except OSError:
                cleaned = False
        return ArtifactRef(
            url=result.url,
            sha256=result.sha256 or digest,
            pending=False,
            cleaned=cleaned,
        )

    def publish_json(
        self,
        payload: dict[str, Any] | list[Any],
        *,
        oss_key: str,
        local_path: Path,
        cleanup: bool = True,
    ) -> ArtifactRef:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.publish_file(local_path, oss_key=oss_key, cleanup=cleanup)

    def url_for_file(self, local_path: Path, *, oss_key: str, cleanup: bool = True) -> str:
        return self.publish_file(local_path, oss_key=oss_key, cleanup=cleanup).url

    def url_for_json(
        self,
        payload: dict[str, Any] | list[Any],
        *,
        oss_key: str,
        local_path: Path,
        cleanup: bool = True,
    ) -> str:
        return self.publish_json(
            payload,
            oss_key=oss_key,
            local_path=local_path,
            cleanup=cleanup,
        ).url

    def ensure_original_url(self, case_id: str) -> str:
        """Upload goldenset original for URL refs. Never deletes the source file."""
        cached = self._original_url_cache.get(case_id)
        if cached:
            return cached

        directory = case_dir(self.loaded.data_root, case_id)
        local: Path | None = None
        for name in ("original.jpg", "original.jpeg", "original.png"):
            candidate = directory / name
            if candidate.is_file():
                local = candidate
                break
        if local is None:
            raise FileNotFoundError(f"original image not found under {directory}")

        ref = self.publish_file(
            local,
            oss_key=f"goldenset/{case_id}/{local.name}",
            cleanup=False,
        )
        self._original_url_cache[case_id] = ref.url
        return ref.url

    @staticmethod
    def sha256_file(path: Path) -> str:
        return sha256_hex(path.read_bytes())

    @staticmethod
    def is_remote_url(url: str | None) -> bool:
        return bool(url and url.startswith(("https://", "http://")))
