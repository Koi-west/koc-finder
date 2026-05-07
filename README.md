# koc-finder

用画像描述你想找的博主，工具负责搜索、打分、出报告。

Find Xiaohongshu (小红书) KOC candidates from a creator persona — search, score, and report.

---

在小红书上找合适的博主，手动做很累。试搜索词、截图、对比内容调性、核查粉丝量——反复几轮下来，花了很多时间，却不一定找得准。

问题不在于搜索不够努力，而在于"合适的博主"是一个画像，不是一个关键词。koc-finder 让你把画像写成 YAML，再把搜索、打分、召回分析这些机械工作交给工具。

Finding the right creators on Xiaohongshu by hand takes too long. You try search terms, screenshot profiles, check follower counts, re-read bios — after a few rounds you've spent hours and still aren't sure the list is right.

The problem is that "right creator" is a persona, not a keyword. koc-finder lets you write the persona as YAML and handles the mechanical work: searching, scoring, and reporting back on what hit and what missed.

## 安装 · Install

把下面这段话发给 Claude Code 或 Codex，AI 会自动完成安装：

Paste the following into Claude Code or Codex — the AI will handle the installation:

```
帮我安装 koc-finder：
1. 运行 pip install git+https://github.com/Koi-west/koc-finder
2. 运行 xhs login --qrcode，等我扫码登录小红书
3. 运行 koc-finder install-skill，帮我选合适的安装目录
安装完成后告诉我可以开始用了。
```

```
Install koc-finder for me:
1. Run pip install git+https://github.com/Koi-west/koc-finder
2. Run xhs login --qrcode and wait for me to scan the QR code
3. Run koc-finder install-skill and help me pick the right install target
Let me know when it's ready.
```

装完后重启 AI 工具，用自然语言描述你想找的博主就行了。

After installation, restart your AI tool and describe the creator you're looking for in natural language — Claude handles the rest.

## 首次使用清单 · Onboarding Checklist

**1. 安装 koc-finder 和 xhs CLI**

```bash
pip install git+https://github.com/Koi-west/koc-finder
pip install xhs
```

**2. 登录小红书（必须）**

```bash
xhs login --qrcode   # 用手机扫码，session 存本地
```

每次 session 过期后重新跑一遍。如果运行途中日志出现 `Session expired`，说明 session 中途失效，评论数据会缺失，建议重新登录后再跑一次。

Run this before each session. If the log shows `Session expired` mid-run, comment data will be missing — re-login and re-run.

**3. 安装飞书 CLI（可选，导出多维表格用）**

两种方式选一种：

Option A — 跟着官方文档装（推荐，AI 可以帮你操作）：
> https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md

Option B — 手动：
```bash
npx @larksuite/cli@latest install
```

装完后登录：
```bash
lark-cli auth login
```

## 每次运行的输出文件 · Output Files

每次运行在 `output/runs/<timestamp>/` 下生成一个独立目录，`output/latest` 符号链接始终指向最新一次：

Each run creates an isolated directory under `output/runs/<timestamp>/`. `output/latest` always points to the most recent run.

```
output/
├── latest -> runs/2026-05-07_163924_.../   # 符号链接，指向最新
├── persona_spec.yaml                        # 本次使用的画像配置
└── runs/
    └── 2026-05-07_163924_.../
        ├── koc_candidates.csv           # 全量：所有打分创作者（100 人），用于备查和手动筛选
        ├── koc_candidates_precision.csv # 精选：自动过滤后的主交付版本（见下方规则）
        ├── koc_candidates_summary.md    # Markdown 摘要，可直接发给合作方
        ├── run_meta.json                # 运行元数据（词包、耗时、错误日志）
        └── retrospective.md             # 自动回顾：哪些词包命中率高，哪些浪费了
```

**精选版过滤规则 · Precision pick rules：**
- Priority A / B：始终入选
- Priority C：仅在被 ≥ 2 个不同词包命中时入选
- Priority Reject：排除
- 排序：优先粉丝层级 1K–5K → 5K–10K → 其他，同层级内按分数降序

**Priority A/B**: always included. **Priority C**: only if hit by ≥ 2 distinct query packs. **Reject**: excluded. Sorted by preferred follower tier (1K–5K first), then score descending.

## 已知局限 · Known Limitations

这个工具还在持续迭代中，以下是目前明确的局限点，后续会逐步改进：

This tool is actively iterated. The following limitations are known and will be addressed over time:

**粉丝数拿不到 · Follower count unavailable**

小红书 API 不在搜索结果或笔记数据里暴露粉丝数；`xhs user <id>` 也频繁返回 `profile_unavailable`。目前只能从均赞数倒推估算（用 `~` 前缀标注），误差可能达一个档位。想确认某个账号真实粉丝数，需要手动打开主页查看。

The XHS API does not expose follower counts in search results or note data. `xhs user <id>` also fails frequently with `profile_unavailable`. Follower tiers are estimated from avg_likes (marked with `~` prefix) and can be off by one tier. Verify manually by opening the profile.

**搜索结果不完整 · Search results are algorithmically curated**

`xhs search` 返回的是平台算法当前推的内容，不是全库查询。再好的词包也不能保证召回某个特定的创作者。`seed_creators` 字段可以强制注入已知账号，但整体覆盖率取决于算法暴露度。

`xhs search` returns algorithmically ranked results, not a full database query. Even perfect queries don't guarantee a specific creator appears. Use `seed_creators` to force-include known accounts.

**打分是弱信号，不是事实判断 · Scores are weak signals, not ground truth**

评分基于公开笔记内容和评论区关键词，无法访问私密数据。Priority A/B 说明值得跟进，不等于一定合适；Reject 说明信号太弱，不等于账号不好。最终判断需要人工审核。

Scores are based on public note content and comment keywords — no private data is accessed. Priority A/B means worth investigating, not "definitely right." Final decisions require human review.

## 致谢 · Credits

见 [CREDITS.md](CREDITS.md)。所有对小红书的读取都通过 [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli)（@jackwener，Apache-2.0）完成。

All Xiaohongshu API access is provided by [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli) by @jackwener (Apache-2.0).

## License

MIT
