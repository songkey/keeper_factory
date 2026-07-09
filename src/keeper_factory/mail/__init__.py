"""SMTP/IMAP mail channel."""

from keeper_factory.mail.approval import (
    apply_approvals,
    clear_batch_approval,
    count_pending_review,
    find_awaiting_batch,
    parse_approval_text,
    parse_approval_with_batch,
)
from keeper_factory.mail.channel import MailChannel, loaded_has_mail_secrets, write_batch_pending_file

__all__ = [
    "MailChannel",
    "apply_approvals",
    "clear_batch_approval",
    "count_pending_review",
    "find_awaiting_batch",
    "loaded_has_mail_secrets",
    "parse_approval_text",
    "parse_approval_with_batch",
    "write_batch_pending_file",
]
