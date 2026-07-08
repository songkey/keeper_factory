from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import oss2
from PIL import Image

from keeper_factory.config import LoadedConfig


class OssUploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadResult:
    url: str
    oss_key: str
    sha256: str | None = None
    pending: bool = False
    local_path: str | None = None


class OssClient:
    """Aliyun OSS upload client with retry."""

    def __init__(self, loaded: LoadedConfig) -> None:
        if loaded.secrets is None:
            raise RuntimeError("OSS client requires resolved secrets")
        cfg = loaded.config.oss
        self.endpoint = cfg.endpoint
        self.bucket_name = cfg.bucket
        self.prefix = cfg.prefix.strip("/")
        self.auth = oss2.Auth(loaded.secrets.oss_access_key, loaded.secrets.oss_secret_key)
        self.bucket = oss2.Bucket(self.auth, self.endpoint, self.bucket_name)
        self.max_retries = 3

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        if self.prefix:
            return f"{self.prefix}/{key}"
        return key

    def get_public_url(self, oss_key: str) -> str:
        endpoint_host = self.endpoint.replace("https://", "").replace("http://", "")
        return f"https://{self.bucket_name}.{endpoint_host}/{oss_key}"

    def _sha256_bytes(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _upload_bytes(self, data: bytes, oss_key: str) -> UploadResult:
        full_key = self._full_key(oss_key)
        last_exc: BaseException | None = None
        for attempt in range(self.max_retries):
            try:
                self.bucket.put_object(full_key, data)
                return UploadResult(
                    url=self.get_public_url(full_key),
                    oss_key=full_key,
                    sha256=self._sha256_bytes(data),
                    pending=False,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(min(2**attempt, 10))
                    continue
        raise OssUploadError(f"OSS upload failed for {full_key}: {last_exc}") from last_exc

    def upload_with_fallback(
        self,
        data: bytes,
        oss_key: str,
        *,
        local_fallback_dir: Path,
    ) -> UploadResult:
        try:
            return self._upload_bytes(data, oss_key)
        except OssUploadError:
            local_fallback_dir.mkdir(parents=True, exist_ok=True)
            local_path = local_fallback_dir / Path(oss_key).name
            local_path.write_bytes(data)
            return UploadResult(
                url="",
                oss_key=self._full_key(oss_key),
                sha256=self._sha256_bytes(data),
                pending=True,
                local_path=str(local_path),
            )

    def upload_image(
        self,
        data: str | Image.Image | np.ndarray,
        oss_key: str,
        *,
        quality: int = 95,
        local_fallback_dir: Path | None = None,
    ) -> UploadResult:
        if isinstance(data, str):
            path = Path(data)
            if not path.is_file():
                raise FileNotFoundError(f"Local file not found: {data}")
            raw = path.read_bytes()
            return self._upload_with_optional_fallback(raw, oss_key, local_fallback_dir)

        if isinstance(data, Image.Image):
            img = data
            if img.mode in ("RGBA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality)
            raw = buffer.getvalue()
            return self._upload_with_optional_fallback(raw, oss_key, local_fallback_dir)

        if isinstance(data, np.ndarray):
            array = np.asarray(data)
            if array.ndim == 3 and array.shape[2] == 3:
                img = Image.fromarray(array.astype(np.uint8), mode="RGB")
            else:
                raise ValueError("numpy image must be HxWx3 RGB array")
            return self.upload_image(img, oss_key, quality=quality, local_fallback_dir=local_fallback_dir)

        raise TypeError("data must be path, PIL.Image, or numpy.ndarray")

    def upload_json(
        self,
        data: dict[str, Any] | list[Any] | str,
        oss_key: str,
        *,
        local_fallback_dir: Path | None = None,
    ) -> UploadResult:
        if isinstance(data, str):
            path = Path(data)
            if not path.is_file():
                raise FileNotFoundError(f"Local JSON file not found: {data}")
            raw = path.read_bytes()
        else:
            raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return self._upload_with_optional_fallback(raw, oss_key, local_fallback_dir)

    def upload_file(
        self,
        file_path: str | Path,
        oss_key: str,
        *,
        local_fallback_dir: Path | None = None,
    ) -> UploadResult:
        path = Path(file_path)
        raw = path.read_bytes()
        return self._upload_with_optional_fallback(raw, oss_key, local_fallback_dir)

    def _upload_with_optional_fallback(
        self,
        raw: bytes,
        oss_key: str,
        local_fallback_dir: Path | None,
    ) -> UploadResult:
        if local_fallback_dir is not None:
            return self.upload_with_fallback(raw, oss_key, local_fallback_dir=local_fallback_dir)
        return self._upload_bytes(raw, oss_key)
