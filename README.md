# koc-finder

用画像描述你想找的博主，工具负责搜索、打分、出报告。

Find Xiaohongshu (小红书) KOC candidates from a creator persona — search, score, and report in one command.

---

在小红书上找合适的博主，手动做很累。试搜索词、截图、对比内容调性、核查粉丝量——反复几轮下来，花了很多时间，却不一定找得准。

问题不在于搜索不够努力，而在于"合适的博主"是一个画像，不是一个关键词。koc-finder 让你把画像写成 YAML，再把搜索、打分、召回分析这些机械工作交给工具。

Finding the right creators on Xiaohongshu by hand takes too long. You try search terms, screenshot profiles, check follower counts, re-read bios — after a few rounds you've spent hours and still aren't sure the list is right.

The problem is that "right creator" is a persona, not a keyword. koc-finder lets you write the persona as YAML and handles the mechanical work: searching, scoring, and reporting back on what hit and what missed.

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

同时安装两个命令：`koc-finder`（本工具）和 `xhs`（小红书 API 客户端，来自 [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli)）。

## Getting Started

### 1. Install

```bash
pip install git+https://github.com/Koi-west/koc-finder
```

Installs `koc-finder` and `xhs` (Xiaohongshu API client via [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli)).

---

### 2. 登录小红书

```bash
xhs login --qrcode  # 终端显示二维码，手机小红书扫码
xhs status --json   # 确认 authenticated: true
```

### 2. Authenticate

```bash
xhs login --qrcode  # QR code appears in terminal — scan with the XHS mobile app
xhs status --json   # verify: authenticated: true
```

---

### 3. 安装 Claude skill

```bash
koc-finder install-skill
```

会问你用的是哪种 Agent 环境：Claude Code、Codex、两者共用（`~/.agents/`），或自定义路径。选"两者共用"时，工具会自动创建 `~/.agents/` 并把两边软链接过去。

安装完后重启 Claude Code / Codex，用 `/xhs-koc-finder` 调用。

### 3. Install the Claude skill

```bash
koc-finder install-skill
```

Prompts you to choose: Claude Code, Codex, both via `~/.agents/`, or a custom path. Choosing "both" automatically creates `~/.agents/` and symlinks both tools' skills directories there.

Restart Claude Code or Codex after installing, then invoke with `/xhs-koc-finder`.

---

### 4. 离线测试

```bash
koc-finder run \
  --persona-yaml examples/v1_persona_spec.yaml \
  --offline examples/v1_fixture.json \
  --output-dir ./output/smoke_test \
  --no-sleep
```

不需要登录，5 秒内完成，验证安装是否正常。

### 4. Offline smoke test

```bash
koc-finder run \
  --persona-yaml examples/v1_persona_spec.yaml \
  --offline examples/v1_fixture.json \
  --output-dir ./output/smoke_test \
  --no-sleep
```

No auth required. Completes in under 5 seconds.

---

### 5. 写画像，跑起来

参照 `examples/v1_persona_spec.yaml` 写你自己的画像，然后：

```bash
koc-finder run --persona-yaml ./my_persona.yaml
```

每次输出在 `output/runs/<timestamp>_<slug>/`：

- `koc_candidates.csv` — 打分后的创作者名单
- `koc_candidates_summary.md` — 可分享的 Markdown 汇总
- `run_meta.json` — 运行统计
- `retrospective.md` — 复盘报告

扩大规模：

```bash
koc-finder run --persona-yaml ./my_persona.yaml --scale large    # 100 人
koc-finder run --persona-yaml ./my_persona.yaml --scale xlarge   # 300 人
```

合并多次结果：

```bash
koc-finder merge --runs-dir ./output/runs/ --output all_candidates.csv
```

### 5. Write a persona and run

Copy `examples/v1_persona_spec.yaml`, edit it for your use case, then:

```bash
koc-finder run --persona-yaml ./my_persona.yaml
```

Output in `output/runs/<timestamp>_<slug>/`:
- `koc_candidates.csv` — scored creator list
- `koc_candidates_summary.md` — shareable Markdown summary
- `run_meta.json` — run stats
- `retrospective.md` — what worked, what missed, what to change

Scale up:

```bash
koc-finder run --persona-yaml ./my_persona.yaml --scale large    # 100 creators
koc-finder run --persona-yaml ./my_persona.yaml --scale xlarge   # 300 creators
```

Merge runs:

```bash
koc-finder merge --runs-dir ./output/runs/ --output all_candidates.csv
```

## 规模参考

| `--scale` | 最大笔记数 | 最大创作者数 | 预估时间 |
|-----------|-----------|------------|---------|
| `normal`  | 60        | 25         | ~10 分钟 |
| `large`   | 200       | 100        | ~25 分钟 |
| `xlarge`  | 600       | 300        | ~90 分钟 |

## Scale Reference

| `--scale` | Max notes | Max creators | Est. time |
|-----------|-----------|-------------|-----------|
| `normal`  | 60        | 25          | ~10 min   |
| `large`   | 200       | 100         | ~25 min   |
| `xlarge`  | 600       | 300         | ~90 min   |

## 常见问题

| 报错 | 解决 |
|------|------|
| `koc-finder: command not found` | 检查 pip scripts 是否在 PATH，或改用 `uv tool install` |
| `xhs: command not found` | `pip install xiaohongshu-cli` |
| `API error -1` | 重新登录：`xhs login --qrcode` |

## Common Errors

| Error | Fix |
|-------|-----|
| `koc-finder: command not found` | check pip scripts are on PATH, or use `uv tool install` |
| `xhs: command not found` | `pip install xiaohongshu-cli` |
| `API error -1` | re-authenticate: `xhs login --qrcode` |

## 致谢

见 [CREDITS.md](CREDITS.md)。所有对小红书的读取都通过 [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli)（@jackwener，Apache-2.0）完成。

## Credits

See [CREDITS.md](CREDITS.md). All Xiaohongshu API access is provided by [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli) by @jackwener (Apache-2.0).

## License

MIT
