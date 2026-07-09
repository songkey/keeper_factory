from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from keeper_factory.ledger.p1 import P1VersionChain, P1VersionRecord
from keeper_factory.util.hashing import sha256_prefix

DEFAULT_CONSTRAINTS = (
    "Treat each candidate as a constrained edit plan toward T0.\n"
    "Prefer minimal, reversible changes over full-scene rewrites.\n"
    "Declare one primary dimension per candidate from the closed vocabulary."
)
DEFAULT_CAPABILITIES = (
    "VLM proposes strategy; a separate edit model executes localized edits.\n"
    "Strategies must be actionable as natural-language edit instructions."
)
DEFAULT_PATTERNS = (
    "Explore diverse dimensions across candidates in the same loop.\n"
    "When evidence is weak, narrow scope instead of adding more instructions."
)


def _jinja_env(prompts_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(prompts_dir)),
        autoescape=select_autoescape(default_for_string=False, default=False),
    )


def bootstrap_slots() -> dict[str, str]:
    return {
        "constraints": DEFAULT_CONSTRAINTS,
        "capabilities": DEFAULT_CAPABILITIES,
        "patterns": DEFAULT_PATTERNS,
    }


def slots_from_record(record: P1VersionRecord) -> dict[str, str]:
    slots = bootstrap_slots()
    for key in ("constraints", "capabilities", "patterns"):
        value = getattr(record, key, None)
        if isinstance(value, str) and value.strip():
            slots[key] = value.strip()
    return slots


def render_p1_text(*, prompts_dir: Path, slots: dict[str, str]) -> str:
    env = _jinja_env(prompts_dir)
    template = env.get_template("p1_initial.jinja")
    return template.render(**slots).strip()


def p1_content_hash(*, prompts_dir: Path, slots: dict[str, str]) -> str:
    return sha256_prefix(render_p1_text(prompts_dir=prompts_dir, slots=slots))


def ensure_p1_bootstrap(
    *,
    prompts_dir: Path,
    p1_chain: P1VersionChain,
    created_loop: int = 0,
) -> tuple[str, dict[str, str]]:
    current = p1_chain.current_version()
    if current:
        record = p1_chain.read_version(current)
        if record is not None:
            return current, slots_from_record(record)

    version = "p1_v001"
    slots = bootstrap_slots()
    record = P1VersionRecord(
        version=version,
        parent=None,
        created_loop=created_loop,
        rationale="initial P.1 bootstrap",
        constraints=slots["constraints"],
        capabilities=slots["capabilities"],
        patterns=slots["patterns"],
    )
    p1_chain.write_version(record)
    p1_chain.set_current_version(version)
    return version, slots


def load_current_p1(
    *,
    prompts_dir: Path,
    p1_chain: P1VersionChain,
) -> tuple[str, dict[str, str], str]:
    version, slots = ensure_p1_bootstrap(prompts_dir=prompts_dir, p1_chain=p1_chain)
    content_hash = p1_content_hash(prompts_dir=prompts_dir, slots=slots)
    return version, slots, content_hash
