from __future__ import annotations

from pathlib import Path
from typing import Any

from keeper_factory.config import LoadedConfig
from keeper_factory.oss import OssClient, OssUploadError
from keeper_factory.util.hashing import sha256_hex


class ArtifactUploader:
    """Upload experiment artifacts to OSS when configured; otherwise keep local file:// URLs."""

    def __init__(self, loaded: LoadedConfig, *, enabled: bool = True) -> None:
        self.loaded = loaded
        self.fallback_dir = loaded.data_root / "ledger" / "artifacts_pending"
        self._client: OssClient | None = None
        if enabled and loaded.secrets is not None:
            try:
                self._client = OssClient(loaded)
            except Exception:
                self._client = None

    def url_for_file(self, local_path: Path, *, oss_key: str) -> str:
        data = local_path.read_bytes()
        if self._client is None:
            return f"file://{local_path.resolve()}"
        try:
            result = self._client.upload_with_fallback(
                data,
                oss_key,
                local_fallback_dir=self.fallback_dir,
            )
            if result.url:
                return result.url
            if result.local_path:
                return f"file://{Path(result.local_path).resolve()}"
        except OssUploadError:
            pass
        return f"file://{local_path.resolve()}"

    def url_for_json(self, payload: dict[str, Any] | list[Any], *, oss_key: str, local_path: Path) -> str:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(
            __import__("json").dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.url_for_file(local_path, oss_key=oss_key)

    @staticmethod
    def sha256_file(path: Path) -> str:
        return sha256_hex(path.read_bytes())
