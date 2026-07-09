from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from keeper_factory import __version__
from keeper_factory.config import find_project_root, load_config
from keeper_factory.init_data import init_from_loaded, seed_demo_from_loaded
from keeper_factory.loop import CheckpointDriftError, LoopRuntime
from keeper_factory.mail import (
    apply_approvals,
    clear_batch_approval,
    find_awaiting_batch,
    parse_approval_text,
    parse_approval_with_batch,
)
from keeper_factory.memory import MemoryStore

app = typer.Typer(
    name="kf",
    help="Keeper Factory MVP — judgment self-evolution lab",
    no_args_is_help=True,
)


def _config_option(
    config: Path = typer.Option(
        Path("config.json"),
        "--config",
        "-c",
        help="Path to config.json",
        exists=False,
        dir_okay=False,
    ),
) -> Path:
    return config


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit",
    ),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def init(
    config: Path = typer.Option(
        Path("config.json"),
        "--config",
        "-c",
        help="Path to config.json",
    ),
    skip_secrets: bool = typer.Option(
        False,
        "--skip-secrets",
        help="Skip environment variable resolution (scaffold only)",
    ),
    skip_checks: bool = typer.Option(
        False,
        "--skip-checks",
        help="Skip OSS/mail environment probes after scaffolding",
    ),
    skip_mail_send: bool = typer.Option(
        False,
        "--skip-mail-send",
        help="Check mail config/DNS but do not send a probe email",
    ),
    skip_oss_write: bool = typer.Option(
        False,
        "--skip-oss-write",
        help="Check OSS config/DNS but do not upload a probe object",
    ),
) -> None:
    """Initialize data/ scaffold and verify env / OSS / mail connectivity."""
    from keeper_factory.healthcheck import run_healthchecks

    root = find_project_root()
    config_path = config if config.is_absolute() else root / config

    if not config_path.is_file():
        example = root / "config.example.json"
        if example.is_file():
            typer.echo(f"Config not found. Copy {example} to {config_path} first.")
        else:
            typer.echo(f"Config not found: {config_path}")
        raise typer.Exit(code=1)

    # Always scaffold first so missing secrets still leave a usable data/ tree.
    scaffold_loaded = load_config(config_path, project_root=root, resolve_secrets=False)
    message = init_from_loaded(scaffold_loaded)
    typer.echo(f"Data root: {scaffold_loaded.data_root}")
    typer.echo(message)

    if skip_secrets or skip_checks:
        typer.echo("Environment checks: skipped")
        if skip_secrets:
            typer.echo("  (use without --skip-secrets to verify OSS/mail on this machine)")
        return

    try:
        loaded = load_config(config_path, project_root=root, resolve_secrets=True)
    except RuntimeError as exc:
        typer.echo("Environment checks:")
        typer.echo(f"  [FAIL] secrets  {exc}")
        typer.echo("Overall: FAILED")
        typer.echo("Init scaffold succeeded, but environment checks failed.")
        raise typer.Exit(code=1) from exc

    report = run_healthchecks(
        loaded,
        check_oss_write=not skip_oss_write,
        check_mail_send=not skip_mail_send,
    )
    for line in report.lines():
        typer.echo(line)
    if not report.ok:
        typer.echo("Init scaffold succeeded, but environment checks failed.")
        raise typer.Exit(code=1)


@app.command("seed-demo")
def seed_demo(
    config: Path = typer.Option(
        Path("config.json"),
        "--config",
        "-c",
        help="Path to config.json",
    ),
    skip_secrets: bool = typer.Option(
        True,
        "--skip-secrets/--resolve-secrets",
        help="Skip environment variable resolution (default: skip)",
    ),
) -> None:
    """Seed a minimal demo goldenset for dry-run E2E."""
    root = find_project_root()
    config_path = config if config.is_absolute() else root / config
    loaded = load_config(config_path, project_root=root, resolve_secrets=not skip_secrets)
    message = seed_demo_from_loaded(loaded)
    typer.echo(f"Data root: {loaded.data_root}")
    typer.echo(message)


@app.command()
def run(
    loops: Optional[int] = typer.Option(None, "--loops", "-n", help="Number of loops to run"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Replay mode without API calls"),
    config: Path = typer.Option(Path("config.json"), "--config", "-c"),
) -> None:
    """Run evolution loops."""
    root = find_project_root()
    config_path = config if config.is_absolute() else root / config
    loaded = load_config(config_path, project_root=root, resolve_secrets=not dry_run)
    runtime = LoopRuntime(loaded, dry_run=dry_run)
    completed = runtime.run(loops=loops)
    typer.echo(f"Completed loops: {', '.join(str(item) for item in completed)}")


@app.command()
def resume(
    force: bool = typer.Option(False, "--force", help="Resume despite config/prompt drift"),
    config: Path = typer.Option(Path("config.json"), "--config", "-c"),
) -> None:
    """Resume from the latest checkpoint."""
    root = find_project_root()
    config_path = config if config.is_absolute() else root / config
    loaded = load_config(config_path, project_root=root)
    runtime = LoopRuntime(loaded, dry_run=False)
    try:
        loop_no = runtime.resume(force=force)
    except CheckpointDriftError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(f"Resumed and completed loop: {loop_no}")


@app.command()
def status(
    config: Path = typer.Option(Path("config.json"), "--config", "-c"),
) -> None:
    """Show current loop/batch/approval status."""
    root = find_project_root()
    config_path = config if config.is_absolute() else root / config
    loaded = load_config(config_path, project_root=root, resolve_secrets=False)
    runtime = LoopRuntime(loaded, dry_run=True)
    snapshot = runtime.status()
    typer.echo(f"running: {snapshot.running}")
    typer.echo(f"loop: {snapshot.loop}")
    typer.echo(f"batch: {snapshot.batch}")
    typer.echo(f"stage: {snapshot.stage}")
    typer.echo(f"pending_review: {snapshot.pending_review_count}")
    typer.echo(f"awaiting_approval: {snapshot.awaiting_approval}")
    typer.echo(f"pending_batch: {snapshot.pending_batch}")
    typer.echo(f"checkpoint_exists: {snapshot.checkpoint_exists}")


@app.command("doctor")
def doctor(
    config: Path = typer.Option(Path("config.json"), "--config", "-c"),
    skip_mail_send: bool = typer.Option(False, "--skip-mail-send"),
    skip_oss_write: bool = typer.Option(False, "--skip-oss-write"),
) -> None:
    """Run environment / OSS / mail probes without re-scaffolding data/."""
    from keeper_factory.healthcheck import run_healthchecks

    root = find_project_root()
    config_path = config if config.is_absolute() else root / config
    loaded = load_config(config_path, project_root=root)
    report = run_healthchecks(
        loaded,
        check_oss_write=not skip_oss_write,
        check_mail_send=not skip_mail_send,
    )
    for line in report.lines():
        typer.echo(line)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("mail-test")
def mail_test(
    config: Path = typer.Option(Path("config.json"), "--config", "-c"),
) -> None:
    """Send a one-off SMTP probe to verify mail configuration."""
    from keeper_factory.healthcheck import CheckStatus, check_mail

    root = find_project_root()
    config_path = config if config.is_absolute() else root / config
    loaded = load_config(config_path, project_root=root)
    results = check_mail(loaded, probe_send=True)
    for item in results:
        typer.echo(f"[{item.status.value}] {item.name}: {item.detail}")
    if any(item.status == CheckStatus.FAIL for item in results):
        raise typer.Exit(code=1)
    typer.echo("Mail probe sent.")


@app.command("oss-test")
def oss_test(
    config: Path = typer.Option(Path("config.json"), "--config", "-c"),
) -> None:
    """Upload a tiny probe object to verify OSS write access."""
    from keeper_factory.healthcheck import CheckStatus, check_oss

    root = find_project_root()
    config_path = config if config.is_absolute() else root / config
    loaded = load_config(config_path, project_root=root)
    results = check_oss(loaded, probe_write=True)
    for item in results:
        typer.echo(f"[{item.status.value}] {item.name}: {item.detail}")
    if any(item.status == CheckStatus.FAIL for item in results):
        raise typer.Exit(code=1)
    typer.echo("OSS probe succeeded.")


@app.command()
def approve(
    config: Path = typer.Option(Path("config.json"), "--config", "-c"),
    batch: int | None = typer.Option(None, "--batch", help="Batch number to approve"),
    file: Path | None = typer.Option(None, "--file", "-f", help="Approval instructions file"),
    text: str | None = typer.Option(None, "--text", help="Inline approval instructions"),
) -> None:
    """Apply batch approval decisions (local fallback for mail channel)."""
    root = find_project_root()
    config_path = config if config.is_absolute() else root / config
    loaded = load_config(config_path, project_root=root)
    data_root = loaded.data_root

    pending_batch = batch or find_awaiting_batch(data_root)
    if pending_batch is None:
        typer.echo("No batch awaiting approval.")
        raise typer.Exit(code=1)

    batch_path = data_root / "ledger" / "batches" / f"batch_{pending_batch:03d}.json"
    if not batch_path.is_file():
        typer.echo(f"Batch file not found: {batch_path}")
        raise typer.Exit(code=1)

    if file is not None:
        approval_text = file.read_text(encoding="utf-8")
    elif text:
        approval_text = text
    else:
        typer.echo("Provide --file or --text with approval lines.")
        raise typer.Exit(code=1)

    memory = MemoryStore(data_root)
    approvals = parse_approval_with_batch(approval_text, batch_path=batch_path)
    if not approvals:
        approvals = parse_approval_text(approval_text)
    if not approvals and "all ok" in approval_text.lower():
        from keeper_factory.mail.approval import ApprovalLine
        from keeper_factory.memory.promotion import PromotionDecision
        from keeper_factory.schemas import KnowledgeStatus

        approvals = [
            ApprovalLine(knowledge_id=doc.id, decision=PromotionDecision.APPROVE)
            for doc in memory.list_all()
            if doc.status == KnowledgeStatus.PENDING_REVIEW
        ]
    if not approvals:
        typer.echo("No valid approval lines parsed.")
        raise typer.Exit(code=1)

    runtime = LoopRuntime(loaded, dry_run=True)
    state = runtime.store.read_runtime_state() or {}
    loop_no = int(state.get("loop") or 0)
    applied = apply_approvals(memory=memory, approvals=approvals, loop=loop_no)
    clear_batch_approval(data_root, batch=pending_batch)
    runtime.store.clear_awaiting_approval()

    for line in applied:
        typer.echo(line)
    typer.echo(f"Batch {pending_batch} approval complete.")


if __name__ == "__main__":
    app()
