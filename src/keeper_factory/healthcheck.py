from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from urllib.parse import urlparse

from keeper_factory.config import LoadedConfig
from keeper_factory.mail import MailChannel, loaded_has_mail_secrets
from keeper_factory.oss import OssClient, OssUploadError


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    WARN = "WARN"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str


@dataclass
class HealthReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(item.status == CheckStatus.FAIL for item in self.results)

    def lines(self) -> list[str]:
        width = max((len(item.name) for item in self.results), default=8)
        out = ["Environment checks:"]
        for item in self.results:
            out.append(f"  [{item.status.value:<4}] {item.name:<{width}}  {item.detail}")
        out.append(f"Overall: {'OK' if self.ok else 'FAILED'}")
        return out


def _check_env_var(name: str, *, required: bool = True) -> CheckResult:
    present = bool(os.environ.get(name))
    if present:
        return CheckResult(name=f"env:{name}", status=CheckStatus.PASS, detail="set")
    if required:
        return CheckResult(
            name=f"env:{name}",
            status=CheckStatus.FAIL,
            detail="missing — export this before real runs",
        )
    return CheckResult(name=f"env:{name}", status=CheckStatus.SKIP, detail="not set")


def _check_dns(host: str, port: int, *, label: str) -> CheckResult:
    try:
        infos = socket.getaddrinfo(host, port)
        return CheckResult(
            name=label,
            status=CheckStatus.PASS,
            detail=f"{host} -> {infos[0][4][0]}",
        )
    except OSError as exc:
        return CheckResult(
            name=label,
            status=CheckStatus.FAIL,
            detail=f"{host}:{port} DNS failed ({exc})",
        )


def check_env(loaded: LoadedConfig) -> list[CheckResult]:
    cfg = loaded.config
    return [
        _check_env_var(cfg.models.api.api_key_env),
        _check_env_var(cfg.oss.access_key_env),
        _check_env_var(cfg.oss.secret_key_env),
        _check_env_var(cfg.mail.password_env),
    ]


def check_oss(loaded: LoadedConfig, *, probe_write: bool = True) -> list[CheckResult]:
    cfg = loaded.config.oss
    results: list[CheckResult] = [
        CheckResult(
            name="oss:config",
            status=CheckStatus.PASS,
            detail=f"bucket={cfg.bucket} endpoint={cfg.endpoint} prefix={cfg.prefix}",
        )
    ]
    host = f"{cfg.bucket}.{urlparse(cfg.endpoint).hostname}"
    results.append(_check_dns(host, 443, label="oss:dns"))

    if loaded.secrets is None:
        results.append(
            CheckResult(
                name="oss:write",
                status=CheckStatus.SKIP,
                detail="secrets not resolved (--skip-secrets)",
            )
        )
        return results

    if not probe_write:
        results.append(
            CheckResult(name="oss:write", status=CheckStatus.SKIP, detail="write probe disabled")
        )
        return results

    if any(item.status == CheckStatus.FAIL for item in results if item.name == "oss:dns"):
        results.append(
            CheckResult(name="oss:write", status=CheckStatus.SKIP, detail="skipped due to DNS failure")
        )
        return results

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"probes/init_oss_{stamp}.txt"
    payload = f"Keeper Factory init OSS probe\nutc={stamp}\n".encode("utf-8")
    try:
        client = OssClient(loaded)
        uploaded = client._upload_bytes(payload, key)
        body = client.bucket.get_object(uploaded.oss_key).read()
        if body != payload:
            results.append(
                CheckResult(name="oss:write", status=CheckStatus.FAIL, detail="readback mismatch")
            )
        else:
            results.append(
                CheckResult(
                    name="oss:write",
                    status=CheckStatus.PASS,
                    detail=f"uploaded {uploaded.oss_key}",
                )
            )
    except OssUploadError as exc:
        results.append(CheckResult(name="oss:write", status=CheckStatus.FAIL, detail=str(exc)))
    except Exception as exc:  # noqa: BLE001
        results.append(
            CheckResult(name="oss:write", status=CheckStatus.FAIL, detail=f"{type(exc).__name__}: {exc}")
        )
    return results


def check_mail(loaded: LoadedConfig, *, probe_send: bool = True) -> list[CheckResult]:
    cfg = loaded.config.mail
    results: list[CheckResult] = [
        CheckResult(
            name="mail:config",
            status=CheckStatus.PASS,
            detail=f"smtp={cfg.smtp_host}:{cfg.smtp_port} from={cfg.from_}",
        )
    ]
    enabled = loaded_has_mail_secrets(loaded)
    if not enabled:
        results.append(
            CheckResult(
                name="mail:enabled",
                status=CheckStatus.WARN,
                detail="disabled (placeholder host or missing password)",
            )
        )
        results.append(
            CheckResult(name="mail:send", status=CheckStatus.SKIP, detail="mail channel disabled")
        )
        return results

    results.append(
        CheckResult(name="mail:enabled", status=CheckStatus.PASS, detail="ready")
    )
    results.append(_check_dns(cfg.smtp_host, cfg.smtp_port, label="mail:dns"))

    if not probe_send:
        results.append(
            CheckResult(name="mail:send", status=CheckStatus.SKIP, detail="send probe disabled")
        )
        return results

    if any(item.status == CheckStatus.FAIL for item in results if item.name == "mail:dns"):
        results.append(
            CheckResult(name="mail:send", status=CheckStatus.SKIP, detail="skipped due to DNS failure")
        )
        return results

    channel = MailChannel(loaded)
    send_result = channel.send_text_detailed(
        subject="[KF][init] environment probe",
        body=(
            "Keeper Factory init mail probe.\n"
            "If you received this, SMTP is configured correctly on this machine.\n"
        ),
    )
    if send_result.ok:
        results.append(
            CheckResult(
                name="mail:send",
                status=CheckStatus.PASS,
                detail=f"sent to {', '.join(cfg.approvers)}",
            )
        )
    else:
        results.append(
            CheckResult(
                name="mail:send",
                status=CheckStatus.FAIL,
                detail=send_result.error or "send failed",
            )
        )
    return results


def run_healthchecks(
    loaded: LoadedConfig,
    *,
    check_oss_write: bool = True,
    check_mail_send: bool = True,
) -> HealthReport:
    report = HealthReport()
    report.results.extend(check_env(loaded))
    report.results.extend(check_oss(loaded, probe_write=check_oss_write))
    report.results.extend(check_mail(loaded, probe_send=check_mail_send))
    return report
