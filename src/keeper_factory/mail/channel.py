from __future__ import annotations

import json
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from keeper_factory.config import LoadedConfig
from keeper_factory.loop.report import markdown_to_html

logger = logging.getLogger(__name__)

_PLACEHOLDER_SMTP_HOSTS = frozenset(
    {
        "",
        "smtp.example.com",
        "example.com",
        "localhost",
    }
)


@dataclass(frozen=True)
class MailSendResult:
    ok: bool
    skipped: bool = False
    error: str | None = None

    def as_summary(self) -> str:
        if self.ok:
            return "mail_sent=True"
        if self.skipped:
            return f"mail_sent=False reason=skipped:{self.error or 'disabled'}"
        return f"mail_sent=False reason={self.error or 'unknown'}"


class MailChannel:
    def __init__(self, loaded: LoadedConfig) -> None:
        self.loaded = loaded
        self.cfg = loaded.config.mail
        self.last_result: MailSendResult | None = None

    @property
    def enabled(self) -> bool:
        return loaded_has_mail_secrets(self.loaded)

    def send_text(
        self,
        *,
        subject: str,
        body: str,
        to_addrs: list[str] | None = None,
    ) -> bool:
        result = self.send_text_detailed(subject=subject, body=body, to_addrs=to_addrs)
        return result.ok

    def send_text_detailed(
        self,
        *,
        subject: str,
        body: str,
        to_addrs: list[str] | None = None,
        html_body: str | None = None,
    ) -> MailSendResult:
        """Best-effort send. Never raises — mail must not block the loop."""
        if not self.enabled or self.loaded.secrets is None:
            result = MailSendResult(ok=False, skipped=True, error="mail_disabled_or_placeholder_host")
            self.last_result = result
            return result
        recipients = to_addrs or list(self.cfg.approvers)
        if not recipients:
            result = MailSendResult(ok=False, skipped=True, error="no_recipients")
            self.last_result = result
            return result

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.cfg.from_
        message["To"] = ", ".join(recipients)
        message.set_content(body)
        if html_body:
            message.add_alternative(html_body, subtype="html")

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                self.cfg.smtp_host,
                self.cfg.smtp_port,
                context=context,
                timeout=30,
            ) as client:
                client.login(self.cfg.username, self.loaded.secrets.mail_password)
                client.send_message(message)
            result = MailSendResult(ok=True)
            self.last_result = result
            return result
        except Exception as exc:  # noqa: BLE001 — mail is optional transport
            err = f"{type(exc).__name__}: {exc}"
            logger.warning("mail send failed (%s): %s", self.cfg.smtp_host, err)
            print(f"[kf mail] send failed via {self.cfg.smtp_host}: {err}", flush=True)
            result = MailSendResult(ok=False, skipped=False, error=err)
            self.last_result = result
            return result

    def send_markdown(
        self,
        *,
        subject: str,
        markdown_body: str,
        to_addrs: list[str] | None = None,
    ) -> MailSendResult:
        """Send multipart plain + HTML rendered from markdown (OSS image URLs embed as <img>)."""
        return self.send_text_detailed(
            subject=subject,
            body=markdown_body,
            to_addrs=to_addrs,
            html_body=markdown_to_html(markdown_body),
        )


def loaded_has_mail_secrets(loaded: LoadedConfig) -> bool:
    if loaded.secrets is None:
        return False
    host = (loaded.config.mail.smtp_host or "").strip().lower()
    if host in _PLACEHOLDER_SMTP_HOSTS or host.endswith(".example.com"):
        return False
    return bool(loaded.secrets.mail_password and host)


def write_batch_pending_file(
    data_root: Path,
    *,
    ledger_root: Path | None = None,
    batch: int,
    loop_end: int,
    pending_items: list[dict[str, str]],
) -> Path:
    base = ledger_root or (data_root / "ledger")
    batches_dir = base / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)
    path = batches_dir / f"batch_{batch:03d}.json"
    payload = {
        "batch": batch,
        "loop_end": loop_end,
        "pending_items": pending_items,
        "decisions": [],
        "awaiting_approval": True,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
