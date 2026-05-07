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

## 致谢 · Credits

见 [CREDITS.md](CREDITS.md)。所有对小红书的读取都通过 [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli)（@jackwener，Apache-2.0）完成。

All Xiaohongshu API access is provided by [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli) by @jackwener (Apache-2.0).

## License

MIT
