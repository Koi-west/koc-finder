---
name: xhs-koc-finder
description: Find and score Xiaohongshu (小红书, XHS, Little Red Book) KOC candidates from a user-provided persona. Use when the user asks to discover KOCs/creators on Xiaohongshu, generate KOC keyword pools, search XHS notes/users, analyze public notes/comments/profiles, score creators, or export KOC candidates to CSV/Markdown for Feishu Base import.
---

# xhs-koc-finder

Use this skill to find Xiaohongshu KOC candidates from a confirmed persona spec and produce a CSV plus Markdown summary.

## Onboarding Checklist

Before the first run, confirm these are installed and authenticated:

### 1. xhs CLI (required)
```bash
pip install xhs          # or: pip3 install xhs
xhs login --qrcode       # scan QR code to authenticate
```

### 2. koc-finder (required)
```bash
pip install koc-finder
```

### 3. lark-cli / Feishu CLI (optional — needed for Feishu export)

Ask the user which method they prefer:

**Option A — Agent install** (follow official guide):
> 参考飞书 CLI 安装文档：https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md

**Option B — Manual install**:
```bash
npx @larksuite/cli@latest install
```

After installing, authenticate:
```bash
lark-cli auth login
```

## Safety Rules

- Use only public, read-only data.
- Do not like, comment, follow, collect, DM, publish, or delete anything.
- Do not ask the user to paste raw cookie values into project files or chat.
- Do not parallelize Xiaohongshu requests.
- If authentication is missing, ask the user to run `xhs login` or `xhs login --qrcode`; never request cookies directly.

## Quick Start

For V1, first confirm the persona with the user, then write `{output_dir}/persona_spec.yaml` and run:

```bash
koc-finder run --persona-yaml ./output/persona_spec.yaml --output-dir ./output
```

Scale up to 100 creators:

```bash
koc-finder run --persona-yaml ./output/persona_spec.yaml --output-dir ./output --scale large
```

Offline smoke test (no auth required):

```bash
koc-finder run \
  --persona-yaml ~/.claude/skills/xhs-koc-finder/examples/v1_persona_spec.yaml \
  --offline ~/.claude/skills/xhs-koc-finder/examples/v1_fixture.json \
  --output-dir ./output/smoke_test \
  --no-sleep
```

Dry-run / validate config:

```bash
koc-finder run --persona-yaml ./output/persona_spec.yaml --validate
```

Merge multiple run results:

```bash
koc-finder merge --runs-dir ./output/runs/ --output merged_candidates.csv
```

## Workflow

1. **Ask at most 4 questions** — focus on what drives query vocabulary, not just persona description:
   - Creator identity + content style (what do they write about, in what tone)
   - **Seed creators**: "你已经知道符合画像的小红书账号吗？哪怕一两个" — add them to `persona_spec.seed_creators` in YAML so they're guaranteed to appear in output via seed rescue (see below)
   - **Ecosystem keywords**: "这个圈子里有哪些标志性活动、社区、黑话？" — events (黑客松/Demo Day/AdventureX), communities (sparklab), jargon (PMF/cap table)
   - Anti-signals, default `中介, 课程, 机构, 广告, 低价申请, 互粉, 抽奖, 加微信`
   - Follower range only if user has an opinion; default `500-50000`

2. **Before writing YAML**: Read `examples/v1_persona_spec.yaml` to confirm format. Do not write from memory.

3. Write confirmed V1 YAML to `{output_dir}/persona_spec.yaml`. **Critical format rules**:
   - `query_packs` is **top-level** (sibling of `persona_spec`, NOT nested inside it)
   - `query_packs` is a **dict keyed by pack name**, not a list: `pack_name: {purpose: "...", queries: [...]}`
   - Wrong: `- name: founder_daily` / Right: `founder_daily: {purpose: "...", queries: [...]}`

4. Run with `koc-finder run` using `run_in_background: true` and NO output truncation (no `| head`, no `| tail`). Capture the full output path from the tool result. Example:
   ```
   Bash: koc-finder run --persona-yaml ... --output-dir ... --scale large
   run_in_background: true
   timeout: 2400000
   ```
   Verify `[info] query packs:` line is non-empty in the captured output before waiting.

5. **Immediately after launching, call `ScheduleWakeup` with the monitoring prompt below** — fill in `OUTPUT_FILE` and `OUTPUT_DIR` from the actual run, then schedule it verbatim. The prompt is self-contained and re-schedules itself every 5 minutes until the run finishes.

   ```
   ScheduleWakeup(
     delaySeconds=300,
     reason="koc-finder 5分钟监控",
     prompt="""
   koc-finder 监控检查。

   OUTPUT_FILE: <paste actual output file path>
   OUTPUT_DIR: <paste actual output/runs/latest path>

   执行步骤：
   1. 运行：wc -l OUTPUT_FILE
   2. 运行：cat OUTPUT_FILE | tail -15
   3. 运行：ps aux | grep koc-finder | grep -v grep
   4. 运行：ls -la OUTPUT_DIR

   判断逻辑：
   - 如果 OUTPUT_DIR 里有 koc_candidates.csv → 任务完成，告诉用户，展示结果摘要（优先级 A/B 的候选人数、总候选人数、输出路径）
   - 如果进程已不存在（ps 无结果）但没有 csv → 任务失败，告诉用户并展示最后几行日志
   - 如果进程存在但 CPU时长 < 2s 且输出行数和上次相同 → 进程冻结，kill PID，重启，告诉用户
   - 如果进程正常运行（有新 pack 进度或 warn 日志）→ 汇报进度，然后用完全相同的 prompt 再次调用 ScheduleWakeup(delaySeconds=300) 继续监控
   """
   )
   ```

6. Each run creates an isolated sub-directory:
   - `output/runs/<timestamp>_<slug>/koc_candidates.csv`
   - `output/runs/<timestamp>_<slug>/koc_candidates_summary.md`
   - `output/runs/<timestamp>_<slug>/run_meta.json`
   - `output/runs/<timestamp>_<slug>/retrospective.md`
   - `output/latest` → symlink to the most recent run

V1 is detected by top-level `persona_spec`. Legacy `persona + keyword_pool` YAML remains supported as V0 mode.

## Seed Rescue

XHS search is algorithmically curated — even perfect query terms don't guarantee a specific creator's notes appear in results (timing, recency, engagement all affect ranking). To guarantee seed accounts always appear in scored output, add their nicknames to `persona_spec.seed_creators`:

```yaml
persona_spec:
  ...
  seed_creators: ["Creator昵称A", "Creator昵称B"]
```

The pipeline searches for each seed by nickname, takes only notes matching that creator, and injects them labelled `query_pack=seed_rescue`. Seed notes bypass pack quotas and are scored alongside normally-collected notes.

**How it works**: After normal pack collection finishes, `rescue_seeds()` runs `xhs search "<nickname>"` for each seed, filters to notes whose `creator_name` matches the nickname, and injects up to 20 notes per creator.

**Critical**: Use the exact XHS nickname (copy from profile), not a display name variant.

## Known CLI Quirks & Bugs

- `xhs user <id>` and `xhs user-posts <id>` frequently return `profile_unavailable` — not a blocker; pipeline continues with blank profile fields.
- `xhs read <note_id> --json` returns empty results or errors. **Never use `--json` flag.** Use `xhs read <note_id>` (no flag) and parse the YAML output directly. (Fixed in pipeline.py: `read()` now uses `_run_yaml()`.)
- `xhslink.com` short links are JS-rendered and cannot be resolved via `curl`. To inspect a creator from a share link, use `xhs search "<nickname>"` to find their `user_id` and note IDs.
- **NEVER pipe `koc-finder` output through `| head`, `| tail`, or any truncating command** — this causes the underlying Python process to receive SIGPIPE and freeze silently at near-zero CPU while appearing alive. Always run with `run_in_background: true` and read the full output file.
- **Frozen process signature**: process alive (`ps aux | grep koc-finder`), CPU time <2s after 5+ minutes, output log not growing → frozen. Fix: kill the PID and restart without any pipe.
- **SSL/network errors per query**: `runner.search()` can throw `RuntimeError` with `[SSL: UNEXPECTED_EOF_WHILE_READING]` or similar transient network errors. As of the fix in `pipeline.py`, each query is individually try/caught — the query logs `[warn] search failed for '<query>': ...` and is skipped; the run continues. If this happens on many queries, check your network/VPN and consider retrying.
- **Session expiry**: if the run log shows `comments failed: Session expired`, the xhs session expired mid-run. Comments data will be missing, which degrades `audience_signals` scoring. Run `xhs login` (or `xhs login --qrcode`) **before** starting a run to avoid this. Session expiry does not abort the run — scores and CSV are still written.
- **Captcha**: occasionally `comments` calls return `Captcha required`. Not fatal — pipeline skips and continues. If it happens frequently, add a longer sleep or pause before retrying.

## Diagnosing a Missing Creator

If a known creator was not found in the output:

1. `xhs search "<nickname>"` — confirm they appear and collect their `note_id`s
2. `xhs read <note_id>` (no `--json`) — read 3–4 notes to extract their actual `tag_list` names and `desc` vocabulary
3. Compare their vocabulary against your `query_packs` — the gap is the miss reason
4. Add a new pack or queries targeting their actual terms (events, jargon, community names)

## Scale Options

| `--scale` | Max notes | Max creators | Sleep/call | Est. time |
|-----------|-----------|-------------|------------|-----------|
| `normal`  | 60        | 25          | 3s         | ~15 min   |
| `large`   | 200       | 100         | 4s         | ~40 min   |
| `xlarge`  | 600       | 300         | 6s         | ~120 min  |

For 1000+ creators: run `--scale xlarge` multiple times across different persona variants, then `koc-finder merge`.

## Output Notes

Each V1 run produces **two CSV files**:

| File | Contents | Use |
|------|----------|-----|
| `koc_candidates.csv` | All 100 scored creators (full backup) | Reference, archival, manual review |
| `koc_candidates_precision.csv` | Precision picks only | Hand to the user as primary deliverable |

**Precision pick rules** (applied to produce `_precision.csv`):
- Priority A/B: always included
- Priority C: included only if hits ≥ 2 distinct discovery packs
- Priority Reject: excluded
- Sort order: preferred tier (1K-5K) first → secondary (5K-10K) → others → score descending within tier

**`follower_tier` field** — added to both CSVs:
- Exact tier (no prefix) when `follower_count` is known: `<1K`, `1K-5K`, `5K-10K`, `10K-50K`, `>50K`
- Estimated tier (`~` prefix) when only `avg_likes` is available: `~1K-5K`, `~5K-10K`, etc.
- **`follower_count` is almost always blank** — XHS API does not expose follower counts in search results or note data. `xhs user <id>` also frequently fails with `profile_unavailable`. There is no reliable way to retrieve follower counts programmatically via this CLI.
- The `~`-prefixed tier is a rough heuristic (avg_likes ≈ 10% of followers for niche micro-influencers). It can be off by one tier in either direction. **Do not present estimated tiers as facts to stakeholders — always note they are estimates. Verify by opening the XHS profile manually if precision matters.**
- Estimation heuristic thresholds: avg_likes ≤ 100 → ~1K, ≤ 500 → ~5K, ≤ 1K → ~10K, ≤ 5K → ~10K-50K, > 5K → ~>50K

Other important field formats:

- `matched_persona`: comma-separated matched keywords, e.g. `留子,founder,tech`
- `audience_signals`: weak proxy summary, e.g. `评论含 VC/AI 词 3 次，note 提及 startup 2 次`
- `profile_url`: use a CLI-returned URL if present; otherwise build `https://www.xiaohongshu.com/user/profile/{xhs_user_id}` only when a reliable ID exists

The Markdown summary must clearly state that Xiaohongshu search is algorithmically exposed content, not a full creator database. Low-exposure but high-quality KOCs may require manual discovery through topics, communities, and comment sections.

## Feishu Export

After a run completes, use `feishu_import.py` (in the output directory) to push the CSV + MD summary into a Feishu Bitable.

### Prerequisites

- `lark-cli` installed: `brew install larksuite/tap/lark-cli` (or `npm i -g @larksuite/cli`)
- Authenticated: `lark-cli auth login`
- Feishu app must have `bitable:app` scope (add in Feishu developer console)

### Usage

```bash
python3 feishu_import.py \
  --csv ./output/runs/<run_id>/koc_candidates.csv \
  --md  ./output/runs/<run_id>/koc_candidates_summary.md \
  --folder-token <your_folder_token>   # optional; empty = root
```

Creates:
- Table 1 **KOC候选人**: all rows from the CSV with typed fields (评分/优先级 as numbers and SingleSelect)
- Table 2 **运行说明**: MD summary split by section

### Known lark-cli quirks

- **Use PUT, not PATCH** for field updates: `PATCH /bitable/v1/apps/.../fields/{field_id}` returns HTTP 404 on Feishu; `PUT` to the same path works.
- **stdout vs stderr**: lark-cli writes the JSON result to stdout on success but to stderr on error (non-zero exit). Read `result.stdout.strip() or result.stderr.strip()` to always get the JSON.
- **GET records requires `bitable:app` permission** in the developer console. Write operations (batch_create) succeed without it, but reads will return `99991679 Permission denied`. The data is still in the table — verify by opening the Feishu URL.
- Use `LARK_CLI_NO_PROXY=1` env var if the machine has an HTTPS proxy that would intercept API calls.

## Resources

- `examples/v1_persona_spec.yaml`: canonical V1 YAML template
- `examples/v1_fixture.json`: offline smoke-test fixture
- `references/scoring_rubric.md`: scoring rules (authoritative spec)
