---
name: xhs-koc-finder
description: Find and score Xiaohongshu (小红书, XHS, Little Red Book) KOC candidates from a user-provided persona. Use when the user asks to discover KOCs/creators on Xiaohongshu, generate KOC keyword pools, search XHS notes/users, analyze public notes/comments/profiles, score creators, or export KOC candidates to CSV/Markdown for Feishu Base import.
---

# xhs-koc-finder

Use this skill to find Xiaohongshu KOC candidates from a confirmed persona spec and produce a CSV plus Markdown summary.

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
   - **Seed creators**: "你已经知道符合画像的小红书账号吗？哪怕一两个" — use these to reverse-engineer vocabulary
   - **Ecosystem keywords**: "这个圈子里有哪些标志性活动、社区、黑话？" — events (黑客松/Demo Day/AdventureX), communities (sparklab), jargon (PMF/cap table)
   - Anti-signals, default `中介, 课程, 机构, 广告, 低价申请, 互粉, 抽奖, 加微信`
   - Follower range only if user has an opinion; default `500-50000`

2. **Before writing YAML**: Read `examples/v1_persona_spec.yaml` to confirm format. Do not write from memory.

3. Write confirmed V1 YAML to `{output_dir}/persona_spec.yaml`. **Critical format rules**:
   - `query_packs` is **top-level** (sibling of `persona_spec`, NOT nested inside it)
   - `query_packs` is a **dict keyed by pack name**, not a list: `pack_name: {purpose: "...", queries: [...]}`
   - Wrong: `- name: founder_daily` / Right: `founder_daily: {purpose: "...", queries: [...]}`

4. Run with `koc-finder run --persona-yaml {output_dir}/persona_spec.yaml`. Verify `[info] query packs:` line is non-empty before waiting for full run.

5. Each run creates an isolated sub-directory:
   - `output/runs/<timestamp>_<slug>/koc_candidates.csv`
   - `output/runs/<timestamp>_<slug>/koc_candidates_summary.md`
   - `output/runs/<timestamp>_<slug>/run_meta.json`
   - `output/runs/<timestamp>_<slug>/retrospective.md`
   - `output/latest` → symlink to the most recent run

V1 is detected by top-level `persona_spec`. Legacy `persona + keyword_pool` YAML remains supported as V0 mode.

## Known CLI Quirks

- `xhs user <id>` and `xhs user-posts <id>` frequently return `profile_unavailable` — not a blocker; pipeline continues with blank profile fields.
- `xhs read <note_id> --json` returns empty results. Use `xhs read <note_id>` (no flag) and parse the YAML output directly.
- `xhslink.com` short links are JS-rendered and cannot be resolved via `curl`. To inspect a creator from a share link, use `xhs search "<nickname>"` to find their `user_id` and note IDs.

## Diagnosing a Missing Creator

If a known creator was not found in the output:

1. `xhs search "<nickname>"` — confirm they appear and collect their `note_id`s
2. `xhs read <note_id>` (no `--json`) — read 3–4 notes to extract their actual `tag_list` names and `desc` vocabulary
3. Compare their vocabulary against your `query_packs` — the gap is the miss reason
4. Add a new pack or queries targeting their actual terms (events, jargon, community names)

## Scale Options

| `--scale` | Max notes | Max creators | Sleep/call | Est. time |
|-----------|-----------|-------------|------------|-----------|
| `normal`  | 60        | 25          | 3s         | ~10 min   |
| `large`   | 200       | 100         | 4s         | ~25 min   |
| `xlarge`  | 600       | 300         | 6s         | ~90 min   |

For 1000+ creators: run `--scale xlarge` multiple times across different persona variants, then `koc-finder merge`.

## Output Notes

CSV fields include: `xhs_user_id`, `xhs_nickname`, `follower_count`, `score`, `priority` (A/B/C/Reject),
`matched_persona`, `audience_signals`, `content_tags`, `sample_notes`, `discovery_queries`, `discovery_packs`,
`high_signal_notes`, `retrieval_reason`, `specificity_signals`, `profile_url`.

Important field formats:

- `matched_persona`: comma-separated matched keywords, e.g. `留子,founder,tech`
- `audience_signals`: weak proxy summary, e.g. `评论含 VC/AI 词 3 次，note 提及 startup 2 次`
- `profile_url`: use a CLI-returned URL if present; otherwise build `https://www.xiaohongshu.com/user/profile/{xhs_user_id}` only when a reliable ID exists

The Markdown summary must clearly state that Xiaohongshu search is algorithmically exposed content, not a full creator database. Low-exposure but high-quality KOCs may require manual discovery through topics, communities, and comment sections.

## Resources

- `examples/v1_persona_spec.yaml`: canonical V1 YAML template
- `examples/v1_fixture.json`: offline smoke-test fixture
- `references/scoring_rubric.md`: scoring rules (authoritative spec)
