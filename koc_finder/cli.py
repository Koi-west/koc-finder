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


@main.command("install-skill")
@click.option(
    "--skills-dir",
    type=click.Path(path_type=Path),
    default=Path.home() / ".claude" / "skills",
    show_default=True,
    help="Target Claude skills directory",
)
def cmd_install_skill(skills_dir: Path) -> None:
    """Copy the bundled Claude skill into ~/.claude/skills/xhs-koc-finder/."""
    here = Path(__file__).parent.parent
    src = here / "skill"
    if not src.exists():
        click.echo(f"[error] skill directory not found at {src}", err=True)
        sys.exit(1)

    dest = skills_dir / "xhs-koc-finder"
    if dest.exists():
        click.confirm(
            f"Skill already installed at {dest}. Overwrite?", abort=True
        )
        shutil.rmtree(dest)

    shutil.copytree(src, dest)
    click.echo(f"[ok] skill installed to {dest}")
    click.echo("     Restart Claude Code (or reload skills) to pick up the change.")


if __name__ == "__main__":
    main()
