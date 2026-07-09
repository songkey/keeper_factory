"""Trimmed OpenAI-only LLM / VLM / image-edit API layer for Keeper Factory v0."""

from __future__ import annotations

import base64
import io
import logging
import os
import re
import time
from typing import Any

import numpy as np
import requests
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


class LLMApiError(RuntimeError):
    """Raised when upstream LLM/image API fails."""


_TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_TRANSIENT_MAX_RETRIES = 2

MIN_PIXELS = 655_360
MAX_PIXELS = 8_294_400
MAX_EDGE = 2048
MAX_RATIO = 3.0
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

_DATA_URL_RE = re.compile(r"data:(image/[^;]+);base64,([A-Za-z0-9+/=\s]+)", re.IGNORECASE)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((data:image/[^)]+)\)", re.IGNORECASE)

_TOKEN_USAGE_MERGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "thinking_tokens",
    "cache_tokens",
    "cache_image_tokens",
    "text_tokens",
    "image_tokens",
)


def is_transient_llm_error(exc: BaseException) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, requests.RequestException):
        return True
    if isinstance(exc, APIStatusError):
        return int(exc.status_code) in _TRANSIENT_HTTP_STATUS_CODES
    if isinstance(exc, LLMApiError):
        message = str(exc).lower()
        if "transport error" in message:
            return True
        match = re.search(r"status=(\d+)", str(exc))
        if match:
            return int(match.group(1)) in _TRANSIENT_HTTP_STATUS_CODES
    return False


def _normalize_sdk_base_url(url: str | None) -> str:
    raw = (url or "").strip().rstrip("/")
    if not raw:
        return DEFAULT_OPENAI_BASE_URL
    if raw.endswith("/chat/completions"):
        return raw[: -len("/chat/completions")]
    if raw.endswith("/v1"):
        return raw
    return raw + "/v1"


def _normalize_api_mode(value: str | None) -> str:
    mode = (value or "openai").strip().lower()
    if mode in {"gpt", "openai"}:
        return "openai"
    if mode in {"auto", "anthropic", "gemini", "google"}:
        return mode
    return "openai"


def _normalize_auth_token(api_key: str) -> str:
    return (api_key or "").strip()


def _safe_token_count(value: Any) -> int | None:
    try:
        if value is None:
            return None
        parsed = int(value)
        return parsed if parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def _usage_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json", exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    return {}


def _reasoning_tokens_from_usage_details(usage_map: dict[str, Any], usage: Any) -> int | None:
    for key in ("completion_tokens_details", "output_tokens_details"):
        details = usage_map.get(key)
        if not isinstance(details, dict):
            details_obj = getattr(usage, key, None)
            details = _usage_mapping(details_obj) if details_obj is not None else {}
        if isinstance(details, dict):
            reasoning = _safe_token_count(details.get("reasoning_tokens"))
            if reasoning is not None:
                return reasoning
    return _safe_token_count(usage_map.get("reasoning_tokens"))


def _cached_input_tokens_from_usage_details(usage_map: dict[str, Any], usage: Any) -> int | None:
    for key in ("prompt_tokens_details", "input_tokens_details"):
        details = usage_map.get(key)
        if not isinstance(details, dict):
            details_obj = getattr(usage, key, None)
            details = _usage_mapping(details_obj) if details_obj is not None else {}
        if isinstance(details, dict):
            cached = _safe_token_count(details.get("cached_tokens"))
            if cached is not None:
                return cached
    return _safe_token_count(usage_map.get("cached_tokens"))


def extract_token_usage_from_response(response: Any) -> dict[str, int | None]:
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    cache_tokens: int | None = None

    usage = getattr(response, "usage", None)
    if usage is not None:
        usage_map = _usage_mapping(usage)
        input_tokens = _safe_token_count(
            usage_map.get("prompt_tokens")
            or usage_map.get("input_tokens")
            or getattr(usage, "prompt_tokens", None)
            or getattr(usage, "input_tokens", None)
        )
        completion_total = _safe_token_count(
            usage_map.get("completion_tokens")
            or usage_map.get("output_tokens")
            or getattr(usage, "completion_tokens", None)
            or getattr(usage, "output_tokens", None)
        )
        thinking_tokens = _reasoning_tokens_from_usage_details(usage_map, usage)
        cache_tokens = _cached_input_tokens_from_usage_details(usage_map, usage)
        if completion_total is not None:
            output_tokens = (
                max(0, completion_total - thinking_tokens)
                if thinking_tokens is not None
                else completion_total
            )
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "thinking_tokens": thinking_tokens,
            "cache_tokens": cache_tokens,
            "cache_image_tokens": None,
            "text_tokens": None,
            "image_tokens": None,
        }

    return {
        "input_tokens": None,
        "output_tokens": None,
        "thinking_tokens": None,
        "cache_tokens": None,
        "cache_image_tokens": None,
        "text_tokens": None,
        "image_tokens": None,
    }


def merge_token_usage(*usages: dict[str, int | None] | None) -> dict[str, int | None]:
    totals = {key: 0 for key in _TOKEN_USAGE_MERGE_KEYS}
    seen = {key: False for key in _TOKEN_USAGE_MERGE_KEYS}
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        for key in _TOKEN_USAGE_MERGE_KEYS:
            value = usage.get(key)
            if value is not None:
                totals[key] += int(value)
                seen[key] = True
    return {key: totals[key] if seen[key] else None for key in _TOKEN_USAGE_MERGE_KEYS}


def _numpy_to_uint8(image: np.ndarray) -> np.ndarray:
    array = np.asarray(image)
    if np.issubdtype(array.dtype, np.floating):
        max_val = float(np.nanmax(array)) if array.size else 0.0
        if max_val <= 1.0 + 1e-3:
            array = np.clip(array, 0.0, 1.0) * 255.0
        else:
            array = np.clip(array, 0.0, 255.0)
    else:
        array = np.clip(array, 0, 255)
    return array.astype(np.uint8)


def _pil_from_numpy(image: np.ndarray) -> Image.Image:
    if not isinstance(image, np.ndarray):
        raise TypeError("image must be a numpy.ndarray")
    if image.ndim == 2:
        return Image.fromarray(_numpy_to_uint8(image), mode="L")
    if image.ndim == 3 and image.shape[2] in (3, 4):
        array = _numpy_to_uint8(image)
        mode = "RGBA" if image.shape[2] == 4 else "RGB"
        return Image.fromarray(array, mode=mode)
    raise ValueError("image must have shape (H, W), (H, W, 3), or (H, W, 4)")


def _download_url_bytes(url: str, timeout_seconds: float) -> bytes:
    response = requests.get(url, timeout=timeout_seconds)
    if response.status_code >= 300:
        body = (response.text or "")[:400]
        raise LLMApiError(
            f"Failed to download image from url={url!r}: status={response.status_code}, body={body}"
        )
    return response.content


def _api_dimensions(
    iw: int,
    ih: int,
    *,
    max_edge: int = MAX_EDGE,
    max_pixels: int = MAX_PIXELS,
) -> tuple[int, int]:
    edge_limit = max(512, int(max_edge))
    pixel_limit = max(MIN_PIXELS, int(max_pixels))
    w, h = float(iw), float(ih)
    for _ in range(64):
        wi = max(16, int(w) // 16 * 16)
        hi = max(16, int(h) // 16 * 16)
        if wi < 16 or hi < 16:
            wi, hi = 16, 16
        long_e, short_e = max(wi, hi), min(wi, hi)
        if long_e > edge_limit:
            scale = edge_limit / long_e
            w, h = wi * scale, hi * scale
            continue
        if short_e > 0 and long_e / short_e > MAX_RATIO:
            if wi >= hi:
                w, h = MAX_RATIO * hi, hi
            else:
                w, h = wi, MAX_RATIO * wi
            continue
        area = wi * hi
        if area < MIN_PIXELS:
            scale = (MIN_PIXELS / area) ** 0.5
            w, h = wi * scale, hi * scale
            continue
        if area > pixel_limit:
            scale = (pixel_limit / area) ** 0.5
            w, h = wi * scale, hi * scale
            continue
        return wi, hi
    wi = max(16, int(w) // 16 * 16)
    hi = max(16, int(h) // 16 * 16)
    return wi, hi


def _image_edit_upload_dimensions(
    src_w: int,
    src_h: int,
    *,
    max_long_edge: int,
    max_pixels: int,
) -> tuple[int, int]:
    """Fit *input* image uploads within max_long_edge / max_pixels (no MIN_PIXELS upscale)."""
    max_long = max(16, int(max_long_edge))
    pixel_limit = max(16 * 16, int(max_pixels))
    w, h = float(src_w), float(src_h)
    long_edge = max(w, h)
    if long_edge > max_long:
        scale = max_long / long_edge
        w *= scale
        h *= scale
    wi = max(16, int(round(w)) // 16 * 16)
    hi = max(16, int(round(h)) // 16 * 16)
    area = wi * hi
    if area > pixel_limit:
        scale = (pixel_limit / area) ** 0.5
        wi = max(16, int(round(wi * scale)) // 16 * 16)
        hi = max(16, int(round(hi * scale)) // 16 * 16)
        long_e = max(wi, hi)
        if long_e > max_long:
            scale = max_long / long_e
            wi = max(16, int(round(wi * scale)) // 16 * 16)
            hi = max(16, int(round(hi * scale)) // 16 * 16)
    return wi, hi


def _ceil_to_multiple(value: float, multiple: int = 16) -> int:
    value = max(float(multiple), float(value))
    return int((value + multiple - 1) // multiple * multiple)


def _image_edit_output_size(
    src_w: int,
    src_h: int,
    *,
    max_long_edge: int | None = None,
) -> tuple[int, int]:
    """Choose a gpt-image-2-legal *output* size (min pixels / edge / ratio constraints).

    Note: ``_api_dimensions`` can land on 800x800 when upscaling from ~512 due to
    truncating to multiples of 16 (800*800 < MIN_PIXELS). Always ceil past the budget.
    """
    edge_cap = MAX_EDGE if max_long_edge is None else max(int(max_long_edge), 1024)
    edge_cap = min(MAX_EDGE, max(1024, edge_cap))

    w = max(1.0, float(src_w))
    h = max(1.0, float(src_h))
    # Ensure we start large enough that after 16-alignment we still meet MIN_PIXELS.
    # 1024x1024 is the safest common preset above the 655_360 budget.
    long_e = max(w, h)
    short_e = min(w, h)
    if long_e * short_e < MIN_PIXELS or long_e < 1024:
        scale = max(1024 / long_e, (MIN_PIXELS / (w * h)) ** 0.5)
        w *= scale
        h *= scale

    wi = min(edge_cap, _ceil_to_multiple(w))
    hi = min(edge_cap, _ceil_to_multiple(h))
    # Preserve aspect if one edge hit the cap.
    if max(wi, hi) == edge_cap and min(w, h) > 0:
        if w >= h:
            hi = max(16, _ceil_to_multiple(edge_cap * (h / w)))
            wi = edge_cap // 16 * 16
        else:
            wi = max(16, _ceil_to_multiple(edge_cap * (w / h)))
            hi = edge_cap // 16 * 16

    # Final safety: bump the short edge until pixel budget is met.
    while wi * hi < MIN_PIXELS:
        if wi <= hi:
            wi = min(edge_cap, wi + 16)
        else:
            hi = min(edge_cap, hi + 16)
        if wi >= edge_cap and hi >= edge_cap:
            break
    if wi * hi < MIN_PIXELS:
        # Last resort: square 1024.
        wi = hi = 1024
    return wi, hi


def _fit_output_to_target_canvas(edited: Image.Image, target_w: int, target_h: int) -> Image.Image:
    edited = edited.convert("RGB")
    ew, eh = edited.size
    if ew <= 0 or eh <= 0 or (ew == target_w and eh == target_h):
        return edited
    if ew >= target_w and eh >= target_h:
        return edited
    scale = max(target_w / ew, target_h / eh)
    nw = max(1, int(round(ew * scale)))
    nh = max(1, int(round(eh * scale)))
    scaled = edited.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - target_w) // 2)
    top = max(0, (nh - target_h) // 2)
    return scaled.crop((left, top, left + target_w, top + target_h))


def _thinking_disabled_extra_body() -> dict[str, Any]:
    return {"thinking": {"type": "disabled"}, "reasoning": {"effort": "none"}}


def _is_openai_reasoning_model(model_name: str) -> bool:
    name = (model_name or "").strip().lower()
    return bool(name) and (name.startswith(("o1", "o3", "o4")) or name.startswith("gpt-5"))


def _is_gpt5_plus_model(model_name: str) -> bool:
    return (model_name or "").strip().lower().startswith("gpt-5")


_GPT5_PLUS_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh"})


def _normalize_reasoning_effort_for_model(
    model_name: str,
    effort: str | None,
    *,
    default: str = "low",
) -> str:
    raw = str(effort or default).strip().lower()
    if _is_gpt5_plus_model(model_name):
        if raw == "minimal":
            raw = "low"
        if raw in _GPT5_PLUS_REASONING_EFFORTS:
            return raw
        return default if default in _GPT5_PLUS_REASONING_EFFORTS else "low"
    return raw or default


def _lightest_reasoning_effort(model_name: str) -> str:
    return _normalize_reasoning_effort_for_model(model_name, "minimal", default="low")


def _chat_completion_token_limit_kwargs(
    effective_max: int | None,
    *,
    thinking_enabled: bool,
) -> dict[str, int]:
    if effective_max is None:
        return {}
    if thinking_enabled:
        return {"max_completion_tokens": effective_max}
    return {"max_tokens": effective_max}


def _is_unsupported_reasoning_param_error(exc: APIStatusError) -> bool:
    return int(exc.status_code or 0) in {400, 422}


def _is_unsupported_max_tokens_error(exc: APIStatusError) -> bool:
    if int(exc.status_code or 0) != 400:
        return False
    body = str(exc).lower()
    return "max_tokens" in body and "max_completion_tokens" in body


def _chat_finish_reason(completion: Any) -> str | None:
    choices = getattr(completion, "choices", None)
    if not choices:
        return None
    reason = getattr(choices[0], "finish_reason", None)
    return reason.strip() if isinstance(reason, str) and reason.strip() else None


def _peek_chat_visible_text(completion: Any) -> str:
    choices = getattr(completion, "choices", None)
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None:
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks).strip()
    return ""


def _chat_content_to_responses_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        text = content.strip()
        return [{"type": "input_text", "text": text}] if text else []
    if isinstance(content, list):
        out: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    out.append({"type": "input_text", "text": text})
            elif item_type == "image_url":
                url_obj = item.get("image_url")
                url = url_obj.get("url") if isinstance(url_obj, dict) else None
                if isinstance(url, str) and url.strip():
                    out.append({"type": "input_image", "image_url": url.strip()})
        return out
    return []


def _messages_to_responses_payload(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    instructions: str | None = None
    input_items: list[dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role") or "user").strip().lower()
        content = msg.get("content", "")
        if role == "system":
            if instructions is None and isinstance(content, str) and content.strip():
                instructions = content.strip()
            continue
        resp_content = _chat_content_to_responses_content(content)
        if resp_content:
            input_role = role if role in {"user", "developer"} else "user"
            input_items.append({"role": input_role, "content": resp_content})
    return instructions, input_items


def _peek_responses_visible_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    output = getattr(response, "output", None) or []
    chunks: list[str] = []
    for item in output:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "output_text":
                text = getattr(part, "text", "")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
    return "\n".join(chunks).strip()


def _empty_chat_completion_error_message(completion: Any, *, model: str) -> str:
    finish_reason = _chat_finish_reason(completion)
    return (
        f"Chat completion response contains empty text (finish_reason={finish_reason}, model={model})"
    )


def _is_multimodal_image_edit_model(model_name: str) -> bool:
    name = (model_name or "").strip().lower()
    return bool(name) and not name.startswith("gpt-image")


def _normalize_image_output_format(value: str | None) -> str:
    fmt = (value or "jpeg").strip().lower()
    if fmt == "jpg":
        return "jpeg"
    return fmt if fmt in {"jpeg", "png", "webp"} else "jpeg"


def _normalize_image_output_compression(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        return min(100, max(0, int(value)))
    except (TypeError, ValueError):
        return None


def _normalize_image_quality(value: str | None) -> str | None:
    quality = (value or "").strip().lower()
    return quality or None


def _resolve_image_edit_int_setting(
    settings: dict[str, Any] | None,
    key: str,
    *,
    default: int,
    minimum: int,
) -> int:
    if isinstance(settings, dict) and settings.get(key) is not None:
        try:
            return max(minimum, int(settings[key]))
        except (TypeError, ValueError):
            pass
    return max(minimum, int(default))


def _resolve_image_edit_max_long_edge(settings: dict[str, Any] | None) -> int:
    return _resolve_image_edit_int_setting(
        settings, "image_edit_max_long_edge", default=512, minimum=16
    )


def _resolve_image_edit_upload_jpeg_quality(settings: dict[str, Any] | None) -> int:
    return min(
        100,
        _resolve_image_edit_int_setting(
            settings, "image_edit_upload_jpeg_quality", default=95, minimum=50
        ),
    )


def _resolve_image_edit_max_pixels(settings: dict[str, Any] | None, *, max_long_edge: int) -> int:
    if isinstance(settings, dict) and settings.get("image_edit_max_pixels") is not None:
        try:
            return max(16 * 16, int(settings["image_edit_max_pixels"]))
        except (TypeError, ValueError):
            pass
    max_long = max(16, int(max_long_edge))
    return max_long * max_long


def _transient_retry_delay(attempt: int) -> None:
    time.sleep(min(2**attempt, 20))


class _BaseAPI:
    def __init__(
        self,
        *,
        api_key: str,
        request_url: str | None,
        model_name: str,
        thinking_enabled: bool = False,
        reasoning_effort: str | None = None,
        timeout_seconds: float = 180.0,
        temperature: float | None = None,
        max_tokens: int | None = None,
        api_mode: str | None = None,
    ) -> None:
        normalized_key = _normalize_auth_token(api_key)
        if not normalized_key:
            raise ValueError("api_key is required")

        self.api_key = normalized_key
        self.request_url = (request_url or "").strip()
        self.base_url = _normalize_sdk_base_url(self.request_url)
        self.model_name = (model_name or "").strip()
        if not self.model_name:
            raise ValueError("model_name is required")
        self.timeout_seconds = float(timeout_seconds)
        self.thinking_enabled = bool(thinking_enabled)
        effort = (reasoning_effort or "").strip().lower()
        self.reasoning_effort = effort or None
        self.temperature = float(temperature) if temperature is not None else None
        self.max_tokens = int(max_tokens) if max_tokens is not None else None
        self.api_mode = _normalize_api_mode(api_mode)
        self._last_token_usage: dict[str, int | None] = {
            key: None for key in _TOKEN_USAGE_MERGE_KEYS
        }
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
        )

    def consume_token_usage(self) -> dict[str, int | None]:
        usage = dict(self._last_token_usage)
        self._reset_token_usage()
        return usage

    def _reset_token_usage(self) -> None:
        self._last_token_usage = {key: None for key in _TOKEN_USAGE_MERGE_KEYS}

    def _capture_token_usage(self, response: Any) -> None:
        usage = extract_token_usage_from_response(response)
        self._last_token_usage = merge_token_usage(self._last_token_usage, usage)

    def _openai_reasoning_payload(self, model: str) -> dict[str, Any]:
        effort = _normalize_reasoning_effort_for_model(model, self.reasoning_effort)
        return {"effort": effort}

    def _openai_reasoning_request_kwargs(self, model: str, *, thinking_enabled: bool) -> dict[str, Any]:
        if not _is_openai_reasoning_model(model) or not thinking_enabled:
            return {}
        return {
            "reasoning_effort": _normalize_reasoning_effort_for_model(model, self.reasoning_effort)
        }

    def _create_responses_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        reasoning: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
    ) -> Any:
        instructions, input_items = _messages_to_responses_payload(messages)
        if not input_items:
            raise LLMApiError("Responses API input is empty after message conversion")
        request_kwargs: dict[str, Any] = {"model": model, "input": input_items}
        if reasoning:
            request_kwargs["reasoning"] = reasoning
        if instructions:
            request_kwargs["instructions"] = instructions
        if max_output_tokens is not None:
            request_kwargs["max_output_tokens"] = int(max_output_tokens)
        try:
            result = self.client.responses.create(**request_kwargs)
            self._capture_token_usage(result)
            return result
        except APIStatusError as exc:
            raise LLMApiError(f"Responses API error: status={exc.status_code}, detail={exc}") from exc
        except (APIConnectionError, APITimeoutError) as exc:
            raise LLMApiError(f"Responses API transport error: {exc}") from exc

    def _create_chat_completion(self, *, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        try:
            result = self.client.chat.completions.create(model=model, messages=messages, **kwargs)
            self._capture_token_usage(result)
            return result
        except APIStatusError as exc:
            if _is_unsupported_max_tokens_error(exc) and "max_tokens" in kwargs:
                retry_kwargs = dict(kwargs)
                retry_kwargs["max_completion_tokens"] = int(retry_kwargs.pop("max_tokens"))
                result = self.client.chat.completions.create(
                    model=model, messages=messages, **retry_kwargs
                )
                self._capture_token_usage(result)
                return result
            raise LLMApiError(
                f"Chat completion API error: status={exc.status_code}, detail={exc}"
            ) from exc
        except (APIConnectionError, APITimeoutError) as exc:
            raise LLMApiError(f"Chat completion transport error: {exc}") from exc

    def _create_chat_completion_without_reasoning(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        extra_body = _thinking_disabled_extra_body()
        strategies: list[tuple[str, dict[str, Any]]] = [
            ("reasoning_effort_none+extra_body", {"reasoning_effort": "none", "extra_body": extra_body}),
            ("reasoning_effort_none", {"reasoning_effort": "none"}),
            ("extra_body_only", {"extra_body": extra_body}),
        ]
        errors: list[str] = []
        for name, strategy_kwargs in strategies:
            try:
                return self._create_chat_completion(
                    model=model, messages=messages, **kwargs, **strategy_kwargs
                )
            except LLMApiError as exc:
                cause = exc.__cause__
                if isinstance(cause, APIStatusError) and _is_unsupported_reasoning_param_error(cause):
                    errors.append(f"{name}: status={cause.status_code}")
                    continue
                raise
        raise LLMApiError(
            "Unable to disable reasoning for this upstream endpoint. "
            f"Details: {'; '.join(errors) if errors else 'no strategy'}"
        )

    def _call_with_transient_retry(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        last_exc: BaseException | None = None
        for attempt in range(_TRANSIENT_MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except (APIConnectionError, APITimeoutError, APIStatusError, LLMApiError) as exc:
                last_exc = exc
                if attempt < _TRANSIENT_MAX_RETRIES and is_transient_llm_error(exc):
                    logger.warning("Transient LLM error (attempt %s): %s", attempt + 1, exc)
                    _transient_retry_delay(attempt)
                    continue
                raise
        if last_exc:
            raise last_exc
        raise LLMApiError("call failed without exception")

    def _chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model_name: str | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        model = (model_name or self.model_name or "").strip()
        if not model:
            raise ValueError("model_name is required")

        extra: dict[str, Any] = {}
        effective_max = int(max_tokens) if max_tokens is not None else self.max_tokens
        extra.update(
            _chat_completion_token_limit_kwargs(
                effective_max, thinking_enabled=self.thinking_enabled
            )
        )

        if self.thinking_enabled and _is_gpt5_plus_model(model) and hasattr(self.client, "responses"):
            try:
                return self._call_with_transient_retry(
                    self._create_responses_completion,
                    model=model,
                    messages=messages,
                    reasoning=self._openai_reasoning_payload(model),
                    max_output_tokens=effective_max,
                )
            except LLMApiError:
                logger.warning("Responses API failed for %s; falling back to chat.completions", model)

        if self.thinking_enabled:
            extra.update(self._openai_reasoning_request_kwargs(model, thinking_enabled=True))
            return self._call_with_transient_retry(
                self._create_chat_completion, model=model, messages=messages, **extra
            )

        return self._call_with_transient_retry(
            self._create_chat_completion_without_reasoning,
            model=model,
            messages=messages,
            **extra,
        )

    def _extract_completion_text(self, completion: Any) -> str:
        if hasattr(completion, "output"):
            text = _peek_responses_visible_text(completion)
            if text:
                return text
            raise LLMApiError("Responses API response contains empty text")
        return self._extract_chat_text(completion, model=self.model_name)

    def _extract_chat_text(self, completion: Any, *, model: str = "") -> str:
        text = _peek_chat_visible_text(completion)
        if text:
            return text
        raise LLMApiError(_empty_chat_completion_error_message(completion, model=model))

    @staticmethod
    def _image_to_data_url(*, image: np.ndarray, max_long_edge: int, image_format: str = "JPEG") -> str:
        pil = ImageOps.exif_transpose(_pil_from_numpy(image))
        w, h = pil.size
        long_edge = max(w, h)
        if long_edge > max_long_edge:
            scale = max_long_edge / float(long_edge)
            pil = pil.resize(
                (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
                Image.Resampling.LANCZOS,
            )
        fmt = (image_format or "JPEG").strip().upper()
        if fmt not in {"PNG", "JPEG", "JPG"}:
            fmt = "JPEG"
        if fmt in {"JPEG", "JPG"} and pil.mode not in {"RGB", "L"}:
            pil = pil.convert("RGB")
        output = io.BytesIO()
        save_format = "JPEG" if fmt in {"JPEG", "JPG"} else "PNG"
        save_kwargs = {"quality": 95} if save_format == "JPEG" else {}
        pil.save(output, format=save_format, **save_kwargs)
        content_type = "image/png" if save_format == "PNG" else "image/jpeg"
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        return f"data:{content_type};base64,{encoded}"

    @staticmethod
    def _ensure_pil_image(image: Image.Image, *, name: str) -> Image.Image:
        if not isinstance(image, Image.Image):
            raise TypeError(f"{name} must be PIL.Image.Image")
        return image

    @classmethod
    def _decode_base64_image(cls, data: str) -> Image.Image:
        cleaned = re.sub(r"\s+", "", (data or "").strip())
        body = cleaned.rstrip("=")
        pad = (-len(body)) % 4
        image_bytes = base64.b64decode(body + ("=" * pad))
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")

    def _extract_image_pil_from_result(self, result: Any) -> Image.Image:
        data = getattr(result, "data", None)
        if not data:
            raise LLMApiError("Image API response has no data")
        item = data[0]
        b64_json = getattr(item, "b64_json", None)
        if b64_json:
            image_bytes = base64.b64decode(b64_json)
            return Image.open(io.BytesIO(image_bytes)).convert("RGB")
        url = getattr(item, "url", None)
        if isinstance(url, str) and url.strip():
            image_bytes = _download_url_bytes(url.strip(), self.timeout_seconds)
            return Image.open(io.BytesIO(image_bytes)).convert("RGB")
        raise LLMApiError("Unsupported image response payload")

    def _extract_image_pil_from_chat_completion(self, completion: Any) -> Image.Image:
        choices = getattr(completion, "choices", None) or []
        if not choices:
            raise LLMApiError("Chat completion response has no choices")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message else None
        if isinstance(content, str):
            for match in _DATA_URL_RE.finditer(content):
                return self._decode_base64_image(match.group(2))
            for match in _MARKDOWN_IMAGE_RE.finditer(content):
                data_url = match.group(1)
                match2 = _DATA_URL_RE.search(data_url)
                if match2:
                    return self._decode_base64_image(match2.group(2))
        raise LLMApiError("Chat completion response contains no image")


class LLMAPI(_BaseAPI):
    """Text LLM API."""

    def generate(
        self,
        *,
        system_prompt: str = "",
        user_prompt: str,
        model_name: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not (user_prompt or "").strip():
            raise ValueError("user_prompt is required")
        messages: list[dict[str, Any]] = []
        if (system_prompt or "").strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": user_prompt.strip()})
        self._reset_token_usage()
        completion = self._chat_completion(
            messages=messages, model_name=model_name, max_tokens=max_tokens
        )
        return self._extract_completion_text(completion)


class VLLMAPI(_BaseAPI):
    """Vision LLM API."""

    def generate(
        self,
        *,
        images: np.ndarray | list[np.ndarray],
        system_prompt: str = "",
        user_prompt: str,
        model_name: str | None = None,
        max_long_edge: int = 512,
        image_format: str = "JPEG",
        max_tokens: int | None = None,
    ) -> str:
        if not (user_prompt or "").strip():
            raise ValueError("user_prompt is required")
        if int(max_long_edge) <= 0:
            raise ValueError("max_long_edge must be > 0")
        image_list = images if isinstance(images, list) else [images]
        if not image_list:
            raise ValueError("images is required")

        content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt.strip()}]
        for image in image_list:
            data_url = self._image_to_data_url(
                image=image, max_long_edge=int(max_long_edge), image_format=image_format
            )
            content.append({"type": "image_url", "image_url": {"url": data_url}})

        messages: list[dict[str, Any]] = []
        if (system_prompt or "").strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": content})
        self._reset_token_usage()
        completion = self._chat_completion(
            messages=messages, model_name=model_name, max_tokens=max_tokens
        )
        return self._extract_completion_text(completion)


class ImageEditAPI(_BaseAPI):
    """Image edit API (OpenAI images.edit; gpt-image models)."""

    def __init__(
        self,
        *,
        api_key: str,
        request_url: str | None,
        model_name: str = "gpt-image-2",
        output_format: str = "jpeg",
        output_compression: int | None = None,
        quality: str | None = None,
        timeout_seconds: float = 180.0,
        api_mode: str | None = None,
        retry_max_loops: int = 1,
    ) -> None:
        super().__init__(
            api_key=api_key,
            request_url=request_url,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            api_mode=api_mode,
        )
        self.output_format = _normalize_image_output_format(output_format)
        self.output_compression = _normalize_image_output_compression(output_compression)
        self.quality = _normalize_image_quality(quality)
        self.image_edit_max_long_edge = _resolve_image_edit_max_long_edge({})
        self.image_edit_max_pixels = _resolve_image_edit_max_pixels(
            {}, max_long_edge=self.image_edit_max_long_edge
        )
        self.image_edit_upload_jpeg_quality = _resolve_image_edit_upload_jpeg_quality({})
        self.retry_max_loops = max(0, int(retry_max_loops))

    def _image_edit_timeout_seconds(self) -> float:
        return max(self.timeout_seconds, float(os.getenv("IMAGE_EDIT_TIMEOUT_SECONDS", "240")))

    def _image_edit_openai_client(self) -> OpenAI:
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self._image_edit_timeout_seconds(),
        )

    def _image_edit_via_chat_completions(
        self,
        *,
        target_model: str,
        prompt: str,
        image_bytes: bytes,
    ) -> Image.Image:
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:image/jpeg;base64,{image_b64}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt.strip()},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]
        client = self._image_edit_openai_client()
        completion = client.chat.completions.create(
            model=target_model,
            messages=messages,
            extra_body={"generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}},
        )
        self._capture_token_usage(completion)
        return self._extract_image_pil_from_chat_completion(completion)

    def image_edit(
        self,
        *,
        image: Image.Image,
        prompt: str,
        mask: Image.Image | None = None,
        model_name: str | None = None,
    ) -> Image.Image:
        if not (prompt or "").strip():
            raise ValueError("prompt is required")
        target_model = (model_name or self.model_name).strip()
        if not target_model:
            raise ValueError("model_name is required")

        self._reset_token_usage()
        source_pil = ImageOps.exif_transpose(self._ensure_pil_image(image, name="image")).convert("RGB")
        src_w, src_h = source_pil.size
        # Input upload can be small (e.g. 512 long edge). Output size must meet API min pixels.
        upload_w, upload_h = _image_edit_upload_dimensions(
            src_w,
            src_h,
            max_long_edge=self.image_edit_max_long_edge,
            max_pixels=self.image_edit_max_pixels,
        )
        out_w, out_h = _image_edit_output_size(src_w, src_h)
        upload_pil = source_pil.resize((upload_w, upload_h), Image.Resampling.LANCZOS)
        upload_buf = io.BytesIO()
        upload_pil.save(upload_buf, format="JPEG", quality=self.image_edit_upload_jpeg_quality)
        image_bytes = upload_buf.getvalue()

        if _is_multimodal_image_edit_model(target_model):
            edited = self._call_with_transient_retry(
                self._image_edit_via_chat_completions,
                target_model=target_model,
                prompt=prompt.strip(),
                image_bytes=image_bytes,
            )
            return _fit_output_to_target_canvas(edited, out_w, out_h)

        kwargs: dict[str, Any] = {
            "model": target_model,
            "image": ("input.jpg", image_bytes, "image/jpeg"),
            "prompt": prompt.strip(),
            "size": f"{out_w}x{out_h}",
            "n": 1,
            "output_format": self.output_format,
        }
        if self.output_compression is not None:
            kwargs["output_compression"] = self.output_compression
        if self.quality:
            kwargs["quality"] = self.quality
        if mask is not None:
            mask_pil = ImageOps.exif_transpose(self._ensure_pil_image(mask, name="mask"))
            if mask_pil.size != (upload_w, upload_h):
                mask_pil = mask_pil.resize((upload_w, upload_h), Image.Resampling.LANCZOS)
            if mask_pil.mode not in {"L", "RGBA"}:
                mask_pil = mask_pil.convert("L")
            mask_buf = io.BytesIO()
            mask_pil.save(mask_buf, format="PNG")
            kwargs["mask"] = ("mask.png", mask_buf.getvalue(), "image/png")

        max_attempts = max(1, 1 + self.retry_max_loops)
        client = self._image_edit_openai_client()
        last_exc: BaseException | None = None
        for attempt in range(max_attempts):
            try:
                result = client.images.edit(**kwargs)
                self._capture_token_usage(result)
                edited = self._extract_image_pil_from_result(result)
                return _fit_output_to_target_canvas(edited, out_w, out_h)
            except (APIStatusError, APIConnectionError, APITimeoutError, LLMApiError) as exc:
                last_exc = exc
                if attempt < max_attempts - 1 and is_transient_llm_error(exc):
                    _transient_retry_delay(attempt)
                    continue
                break
        raise LLMApiError(f"Image edit failed: {last_exc}")
