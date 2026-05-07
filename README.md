# xhs-koc-finder

Find and score Xiaohongshu (小红书) KOC candidates via persona-driven search.

Define a creator persona in YAML, run one command, get a scored CSV + Markdown summary + run retrospective.

## Features

- **Persona-driven search** — write what kind of creator you want; the tool builds search queries from your vocabulary
- **Per-run isolation** — each run gets its own timestamped directory; nothing is ever overwritten
- **Retrospective report** — auto-generated pack efficiency analysis, zero-recall query detection, vocab gap suggestions
- **Scale modes** — 25 / 100 / 300 creators in one run; merge multiple runs for 1000+
- **Dry-run validation** — `--validate` prints config analysis and estimated runtime without touching XHS

## Getting Started

### 1. Install

```bash
pip install xhs-koc-finder
# or with uv (recommended):
uv tool install xhs-koc-finder
```

This installs `koc-finder` and its dependency `xiaohongshu-cli` (the `xhs` command).

### 2. Authenticate with Xiaohongshu

```bash
xhs --version       # verify installation
xhs login --qrcode  # scan QR code in terminal
xhs status --json   # should show authenticated: true
```

### 3. Install the Claude skill (optional)

If you use Claude Code and want the AI-assisted workflow:

```bash
koc-finder install-skill
```

Then restart Claude Code. The skill will guide persona creation and pipeline runs.

### 4. Offline smoke test

Run without any XHS auth to verify the installation:

```bash
koc-finder run \
  --persona-yaml examples/v1_persona_spec.yaml \
  --offline examples/v1_fixture.json \
  --output-dir ./output/smoke_test \
  --no-sleep
```

Expected: completes in < 5 seconds, creates `output/smoke_test/runs/<timestamp>/`.

### 5. Write your persona

Copy `examples/v1_persona_spec.yaml` and edit it:

```yaml
persona_spec:
  creator_profile:
    identity: 留子博主，人在湾区，生活向内容为主
    follower_range: 500-30000
    must_have:
      - 真实个人内容
      - 非机构/中介号
  content_evidence:
    signal_keywords:
      - openclaw
      - adventurex
      - hackathon
      - 湾区
      - 创业
      - founder
    anti_signals:
      - 中介
      - 课程
      - 广告

query_packs:
  ecosystem_events:
    purpose: 圈层标志性活动词
    queries:
      - openclaw 留学生
      - adventurex 留子
      - hackathon 湾区
      - 黑客松 留子
  bay_area_daily:
    purpose: 湾区/硅谷留子日常
    queries:
      - 湾区 留子 日常
      - 硅谷 留学生 生活
      - 湾区 创业 日常
```

### 6. Run

```bash
koc-finder run --persona-yaml ./my_persona.yaml
```

Output in `output/runs/<timestamp>_<slug>/`:
- `koc_candidates.csv` — scored creator list
- `koc_candidates_summary.md` — Markdown summary for sharing
- `run_meta.json` — machine-readable run stats
- `retrospective.md` — postmortem: what worked, what to improve

Scale up:

```bash
koc-finder run --persona-yaml ./my_persona.yaml --scale large    # 100 creators
koc-finder run --persona-yaml ./my_persona.yaml --scale xlarge   # 300 creators
```

Merge multiple runs:

```bash
koc-finder merge --runs-dir ./output/runs/ --output all_candidates.csv
```

## Scale Reference

| `--scale` | Max notes | Max creators | Est. time |
|-----------|-----------|-------------|-----------|
| `normal`  | 60        | 25          | ~10 min   |
| `large`   | 200       | 100         | ~25 min   |
| `xlarge`  | 600       | 300         | ~90 min   |

For 1000+ creators: run multiple times with varied personas, then `koc-finder merge`.

## Common Errors

| Error | Fix |
|-------|-----|
| `koc-finder: command not found` | `uv tool install xhs-koc-finder` or add pip scripts to PATH |
| `xhs: command not found` | `uv tool install xiaohongshu-cli` |
| `API error -1` from xhs | Re-authenticate: `xhs login --qrcode` |
| `PyYAML not found` | `pip install pyyaml` (should be auto-installed with the package) |
| Smoke test overwrites real output | Always use `--output-dir ./output/smoke_test` for smoke tests |

## Credits

See [CREDITS.md](CREDITS.md).

## License

MIT
