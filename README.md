# koc-finder

用画像描述你想找的博主，工具负责搜索、打分、出报告。

Find Xiaohongshu (小红书) KOC candidates from a creator persona — search, score, and report.

---

在小红书上找合适的博主，手动做很累。试搜索词、截图、对比内容调性、核查粉丝量——反复几轮下来，花了很多时间，却不一定找得准。

问题不在于搜索不够努力，而在于"合适的博主"是一个画像，不是一个关键词。koc-finder 让你把画像写成 YAML，再把搜索、打分、召回分析这些机械工作交给工具。

Finding the right creators on Xiaohongshu by hand takes too long. You try search terms, screenshot profiles, check follower counts, re-read bios — after a few rounds you've spent hours and still aren't sure the list is right.

The problem is that "right creator" is a persona, not a keyword. koc-finder lets you write the persona as YAML and handles the mechanical work: searching, scoring, and reporting back on what hit and what missed.

## 安装 · Install

```bash
pip install git+https://github.com/Koi-west/koc-finder
```

登录小红书 · Authenticate:

```bash
xhs login --qrcode
```

安装 Claude skill · Install the Claude skill:

```bash
koc-finder install-skill
```

会问你用的是 Claude Code、Codex，还是两者共用。装完后重启 AI 工具，之后直接用自然语言告诉 Claude 你想找什么样的博主就行了。

You'll be asked whether you use Claude Code, Codex, or both. After installation, restart your AI tool and describe the creator you're looking for in natural language — Claude handles the rest.

## 致谢 · Credits

见 [CREDITS.md](CREDITS.md)。所有对小红书的读取都通过 [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli)（@jackwener，Apache-2.0）完成。

All Xiaohongshu API access is provided by [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli) by @jackwener (Apache-2.0).

## License

MIT
