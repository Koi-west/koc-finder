"""CLI entry point for koc-finder."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

from koc_finder import __version__


@click.group()
@click.version_option(__version__, prog_name="koc-finder")
def main() -> None:
    """Find and score Xiaohongshu KOC candidates via persona-driven search."""


@main.command("run")
@click.option(
    "--persona-yaml",
    type=click.Path(exists=True, path_type=Path),
    help="Path to persona_spec.yaml",
)
@click.option(
    "--offline",
    "offline_json",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Offline fixture JSON (skips real XHS calls)",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("output"),
    show_default=True,
    help="Base output directory; a timestamped run sub-dir is created inside it",
)
@click.option(
    "--scale",
    type=click.Choice(["normal", "large", "xlarge"]),
    default="normal",
    show_default=True,
    help="normal=25 creators, large=100, xlarge=300",
)
@click.option(
    "--validate",
    is_flag=True,
    default=False,
    help="Dry-run: parse config and print analysis without making any XHS calls",
)
@click.option(
    "--no-sleep",
    is_flag=True,
    default=False,
    help="Disable rate-limit sleeps (for offline/test use only)",
)
@click.option(
    "--flat",
    is_flag=True,
    default=False,
    help="Write outputs directly to --output-dir instead of a timestamped sub-dir",
)
def cmd_run(
    persona_yaml: Path | None,
    offline_json: Path | None,
    output_dir: Path,
    scale: str,
    validate: bool,
    no_sleep: bool,
    flat: bool,
) -> None:
    """Run the KOC-finder pipeline."""
    from koc_finder.pipeline import run

    if not validate and persona_yaml is None:
        raise click.UsageError("--persona-yaml is required unless --validate is passed")

    exit_code = run(
        persona_yaml=persona_yaml,
        persona_text=None,
        offline_json=offline_json,
        output_base=output_dir,
        scale=scale,
        no_sleep=no_sleep,
        validate=validate,
        use_run_dir=not flat,
    )
    sys.exit(exit_code)


@main.command("merge")
@click.option(
    "--runs-dir",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Directory containing multiple run sub-dirs (each with koc_candidates.csv)",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("merged_candidates.csv"),
    show_default=True,
    help="Path for the merged output CSV",
)
def cmd_merge(runs_dir: Path, output: Path) -> None:
    """Merge multiple run CSVs into one, deduplicating by xhs_user_id."""
    from koc_finder.pipeline import merge_runs

    count = merge_runs(runs_dir, output)
    click.echo(f"[info] merged {count} unique creators → {output}")


_SETUP_OPTIONS = [
    ("claude",  "Claude Code only",           "~/.claude/skills/"),
    ("codex",   "Codex only",                 "~/.codex/skills/"),
    ("agents",  "Both (via ~/.agents/)",      "~/.agents/  ← single source of truth for all tools"),
    ("custom",  "Custom path",                "I'll type the path myself"),
]


def _pick_skills_dir() -> Path:
    """Interactive prompt: ask the user which setup they have."""
    click.echo()
    click.echo("Where should the skill be installed?")
    click.echo()
    for i, (_, label, note) in enumerate(_SETUP_OPTIONS, 1):
        click.echo(f"  {i}. {label}")
        click.echo(f"     {note}")
    click.echo()

    while True:
        raw = click.prompt("Enter number", default="1")
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(_SETUP_OPTIONS):
                break
        except ValueError:
            pass
        click.echo("  Please enter 1–4.")

    key = _SETUP_OPTIONS[idx][0]

    if key == "claude":
        return Path.home() / ".claude" / "skills"

    if key == "codex":
        return Path.home() / ".codex" / "skills"

    if key == "agents":
        agents = Path.home() / ".agents"
        if not agents.exists():
            click.echo()
            click.echo(f"  ~/.agents does not exist yet.")
            click.echo(f"  This will create it and symlink both tools' skills dirs to it.")
            click.confirm("  Continue?", abort=True)
            agents.mkdir()
            _setup_agents_symlinks(agents)
            click.echo(f"  [ok] ~/.agents created and symlinked")
        return agents

    # custom
    raw_path = click.prompt("Enter full path")
    return Path(raw_path).expanduser()


def _setup_agents_symlinks(agents: Path) -> None:
    """Point ~/.claude/skills and ~/.codex/skills at ~/.agents, migrating existing content."""
    for skills_dir in [
        Path.home() / ".claude" / "skills",
        Path.home() / ".codex" / "skills",
    ]:
        if skills_dir.exists() and not skills_dir.is_symlink():
            for item in skills_dir.iterdir():
                dest = agents / item.name
                if not dest.exists():
                    shutil.copytree(item, dest) if item.is_dir() else shutil.copy2(item, dest)
            shutil.rmtree(skills_dir)
        elif skills_dir.is_symlink():
            skills_dir.unlink()
        skills_dir.parent.mkdir(parents=True, exist_ok=True)
        skills_dir.symlink_to(agents)


@main.command("install-skill")
@click.option(
    "--skills-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Skip the interactive prompt and install directly to this path",
)
def cmd_install_skill(skills_dir: Path | None) -> None:
    """Install the bundled Claude / Codex skill.

    Prompts you to choose your setup (Claude Code, Codex, both, or custom).
    Pass --skills-dir to skip the prompt.
    """
    here = Path(__file__).parent.parent
    src = here / "skill"
    if not src.exists():
        click.echo(f"[error] skill bundle not found at {src}", err=True)
        sys.exit(1)

    if skills_dir is None:
        skills_dir = _pick_skills_dir()

    dest = skills_dir / "xhs-koc-finder"
    if dest.exists():
        click.confirm(f"\nSkill already installed at {dest}. Overwrite?", abort=True)
        shutil.rmtree(dest)

    skills_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    click.echo(f"\n[ok] skill installed to {dest}")
    click.echo("     Restart Claude Code / Codex to pick up the change.")


if __name__ == "__main__":
    main()
