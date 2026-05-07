# koc-finder

用画像描述你想找的博主，工具负责搜索、打分、出报告。

Find Xiaohongshu (小红书) KOC candidates from a creator persona — search, score, and report in one command.

---

找小红书博主这件事，手动做很累。搜索词试了一遍又一遍，截图发到飞书，再一个个对着看粉丝量、看内容调性——三个小时过去，也许找到五个人，也许一个都没留下。

我想找的不是粉丝多的，是粉丝对的。留子博主，生活向，但粉丝里有 founder、投资人、tech 圈的人。这种画像，搜索框不认识，只能靠关键词间接逼近。所以我做了这个工具：把画像写成 YAML，工具帮你把搜索词铺开、把博主捞回来、打分、告诉你哪些 pack 白跑了、下次怎么改。

Finding KOC candidates on Xiaohongshu by hand is slow. You search, screenshot, paste into a spreadsheet, check follower counts, re-read bios — three hours in and you might have five names, or none. I needed creators whose followers were right, not just creators who were big. Overseas Chinese students with a Bay Area / startup audience. That's not a search query; it's a persona. So I built a tool that takes the persona as YAML and turns it into a structured search: collect notes, group by creator, score against the persona, write a retrospective on what missed and why.

## 功能

- **画像驱动搜索** — 用 YAML 描述你要找的创作者，工具自动展开查询词
- **每次 Run 独立存储** — 带时间戳的目录，不覆盖历史结果
- **自动复盘报告** — 哪个 pack 高效、哪些词零召回、下次怎么调
- **三档规模** — 单次 25 / 100 / 300 人，多次合并可达 1000+
- **干跑验证** — `--validate` 解析配置、估算耗时，不发任何请求

## Features

- **Persona-driven search** — describe the creator you want in YAML; queries are built from your vocabulary
- **Per-run isolation** — timestamped output directory per run; nothing is ever overwritten
- **Auto retrospective** — pack efficiency table, zero-recall query list, vocabulary gap suggestions
- **Three scale modes** — 25 / 100 / 300 creators per run; merge runs for 1000+
- **Dry-run validation** — `--validate` parses config and estimates runtime without touching XHS

## 快速开始

### 1. 安装

```bash
pip install git+https://github.com/Koi-west/koc-finder
```

这一条指令同时安装两个命令：
- `koc-finder` — 本工具的 CLI
- `xhs` — 小红书 API 客户端（来自 [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli)）

## Getting Started

### 1. Install

```bash
pip install git+https://github.com/Koi-west/koc-finder
```

Installs two commands:
- `koc-finder` — this tool's CLI
- `xhs` — Xiaohongshu API client (via [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli))

---

### 2. 登录小红书

```bash
xhs login --qrcode  # 终端里会出现二维码，用手机小红书扫码
xhs status --json   # 确认 authenticated: true
```

### 2. Authenticate with Xiaohongshu

```bash
xhs login --qrcode  # a QR code appears in the terminal — scan with your XHS mobile app
xhs status --json   # verify: authenticated: true
```

---

### 3. 安装 Claude skill

```bash
koc-finder install-skill
```

会问你用的是哪种 Agent 环境：

```
Where should the skill be installed?

  1. Claude Code only        → ~/.claude/skills/
  2. Codex only              → ~/.codex/skills/
  3. Both (via ~/.agents/)   → ~/.agents/  ← 两个工具共用一个目录
  4. Custom path             → 自己输路径
```

选 3 时，如果 `~/.agents/` 不存在，工具会自动创建并把两边的 skills 目录都软链接过去，一次解决。

安装完后重启 Claude Code / Codex，之后直接 `/xhs-koc-finder` 调用。

### 3. Install the Claude skill

```bash
koc-finder install-skill
```

An interactive prompt asks where to install:

```
  1. Claude Code only        → ~/.claude/skills/
  2. Codex only              → ~/.codex/skills/
  3. Both (via ~/.agents/)   → ~/.agents/  ← single source of truth for all tools
  4. Custom path             → enter manually
```

Option 3: if `~/.agents/` does not exist yet, the tool creates it and symlinks both tools' skills directories there automatically. All future skill installs land in one place.

Restart Claude Code or Codex after installing. Invoke with `/xhs-koc-finder`.

---

### 4. 离线测试（不需要登录）

```bash
koc-finder run \
  --persona-yaml examples/v1_persona_spec.yaml \
  --offline examples/v1_fixture.json \
  --output-dir ./output/smoke_test \
  --no-sleep
```

5 秒内完成，输出到 `output/smoke_test/runs/<timestamp>/`。

### 4. Offline smoke test (no auth required)

```bash
koc-finder run \
  --persona-yaml examples/v1_persona_spec.yaml \
  --offline examples/v1_fixture.json \
  --output-dir ./output/smoke_test \
  --no-sleep
```

Completes in under 5 seconds. Output lands in `output/smoke_test/runs/<timestamp>/`.

---

### 5. 写你的画像

复制 `examples/v1_persona_spec.yaml` 改掉：

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
  bay_area_daily:
    purpose: 湾区/硅谷留子日常
    queries:
      - 湾区 留子 日常
      - 硅谷 留学生 生活
```

### 5. Write your persona

Copy `examples/v1_persona_spec.yaml` and edit it. The two top-level keys are `persona_spec` (who you're looking for) and `query_packs` (how to find them).

---

### 6. 跑起来

```bash
koc-finder run --persona-yaml ./my_persona.yaml
```

每次 Run 的输出在 `output/runs/<timestamp>_<slug>/`：

- `koc_candidates.csv` — 打分后的创作者名单
- `koc_candidates_summary.md` — 可分享的 Markdown 汇总
- `run_meta.json` — 机器可读的运行统计
- `retrospective.md` — 复盘：哪个 pack 有效、哪些词没跑出来、下次怎么改

扩大规模：

```bash
koc-finder run --persona-yaml ./my_persona.yaml --scale large    # 100 人
koc-finder run --persona-yaml ./my_persona.yaml --scale xlarge   # 300 人
```

合并多次结果（去重，同一人取最高分）：

```bash
koc-finder merge --runs-dir ./output/runs/ --output all_candidates.csv
```

### 6. Run

```bash
koc-finder run --persona-yaml ./my_persona.yaml
```

Each run writes to `output/runs/<timestamp>_<slug>/`:
- `koc_candidates.csv` — scored creator list
- `koc_candidates_summary.md` — shareable Markdown summary
- `run_meta.json` — machine-readable run stats
- `retrospective.md` — what worked, what didn't, what to change next time

Scale up:

```bash
koc-finder run --persona-yaml ./my_persona.yaml --scale large    # 100 creators
koc-finder run --persona-yaml ./my_persona.yaml --scale xlarge   # 300 creators
```

Merge multiple runs, deduplicated by creator ID:

```bash
koc-finder merge --runs-dir ./output/runs/ --output all_candidates.csv
```

## 规模参考

| `--scale` | 最大笔记数 | 最大创作者数 | 预估时间 |
|-----------|-----------|------------|---------|
| `normal`  | 60        | 25         | ~10 分钟 |
| `large`   | 200       | 100        | ~25 分钟 |
| `xlarge`  | 600       | 300        | ~90 分钟 |

1000+ 人：多次 run 不同画像，再 `koc-finder merge` 合并。

## Scale Reference

| `--scale` | Max notes | Max creators | Est. time |
|-----------|-----------|-------------|-----------|
| `normal`  | 60        | 25          | ~10 min   |
| `large`   | 200       | 100         | ~25 min   |
| `xlarge`  | 600       | 300         | ~90 min   |

For 1000+ creators: run multiple times with varied personas, then `koc-finder merge`.

## 常见问题

| 报错 | 解决 |
|------|------|
| `koc-finder: command not found` | 检查 pip 的 scripts 目录是否在 PATH，或改用 `uv tool install` |
| `xhs: command not found` | `pip install xiaohongshu-cli` |
| `API error -1` | 重新登录：`xhs login --qrcode` |
| smoke test 覆盖了真实输出 | smoke test 用 `--output-dir ./output/smoke_test` 指定独立目录 |

## Common Errors

| Error | Fix |
|-------|-----|
| `koc-finder: command not found` | check pip scripts are on PATH, or use `uv tool install` |
| `xhs: command not found` | `pip install xiaohongshu-cli` |
| `API error -1` from xhs | re-authenticate: `xhs login --qrcode` |
| smoke test overwrites real output | always pass `--output-dir ./output/smoke_test` for smoke tests |

## 致谢

见 [CREDITS.md](CREDITS.md)。这个工具站在 [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli)（@jackwener，Apache-2.0）的肩膀上——所有对小红书的读取都由它完成。

## Credits

See [CREDITS.md](CREDITS.md). This tool is built on top of [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli) by @jackwener (Apache-2.0) — all Xiaohongshu API access goes through it.

## License

MIT
