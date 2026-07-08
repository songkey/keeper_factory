from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from keeper_factory import __version__
from keeper_factory.config import find_project_root, load_config
from keeper_factory.init_data import init_from_loaded, seed_demo_from_loaded
from keeper_factory.loop import CheckpointDriftError, LoopRuntime

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
) -> None:
    """Initialize the nested data/ git repository and directory scaffold."""
    root = find_project_root()
    config_path = config if config.is_absolute() else root / config

    if not config_path.is_file():
        example = root / "config.example.json"
        if example.is_file():
            typer.echo(f"Config not found. Copy {example} to {config_path} first.")
        else:
            typer.echo(f"Config not found: {config_path}")
        raise typer.Exit(code=1)

    loaded = load_config(config_path, project_root=root, resolve_secrets=not skip_secrets)
    message = init_from_loaded(loaded)
    typer.echo(f"Data root: {loaded.data_root}")
    typer.echo(message)


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
    typer.echo(f"checkpoint_exists: {snapshot.checkpoint_exists}")


@app.command()
def approve(
    config: Path = typer.Option(Path("config.json"), "--config", "-c"),
) -> None:
    """Local approval fallback when mail is unavailable (not yet implemented)."""
    typer.echo("kf approve is not implemented yet.")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
