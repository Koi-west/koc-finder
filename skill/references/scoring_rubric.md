# xhs-koc-finder Scoring Rubric

V1 total before risk deduction: 100 points.

## 画像匹配度: 35

Use weighted unique hits, not raw frequency.

```text
signal_hits = unique matched signal_keywords + unique matched specificity marker values
ordinary_hits = unique matched creator identity/content/style terms

weighted_hits = len(signal_hits) * 2 + len(ordinary_hits)
weighted_cap = min(20, len(all_signal_keywords) * 2 + len(all_ordinary_terms))
persona_score = min(35, round(weighted_hits / max(1, weighted_cap) * 35))
```

## 内容真实感: 20

Reward first-person life records, concrete experiences, varied daily content, and non-institutional tone.

Positive signals:

- 我、我的、自己、今天、日常、记录、生活、搬家、租房、实习、毕业、找工作
- Multiple recent notes with varied titles
- Personal story language rather than service copy

Negative signals:

- 机构、中介、顾问、报名、领取资料、加微信、课程、低价申请

## 内容具体度 / specificity: 15

- Concrete school/conference/score/product/company markers in notes: +3 each, max +9
- Multiple consistent high-signal notes rather than one-off viral note: +3
- Concrete identity info in bio: +3
- Pure 留子/vlog/日常 tags without concrete evidence do not score specificity points

## 互动质量: 10

Comments are used only to judge discussion quality.

Positive signals:

- Specific questions or replies
- Real discussion with concrete nouns
- Longer comments that respond to the content

Negative signals:

- 互粉、抽奖、求链接、蹲、dd、已私、机器人-like short repeats

## 商业合作自然植入: 10

Text-only proxy from title/body/tags. Do not infer from images.

Positive signals:

- Clear writing
- Stable content style
- Natural product mentions in text
- App/tool/life workflow scenes that could support soft product placement

Negative signals:

- 广告、合作、课程、私信链接、🔗、低价、机构 framing
- Hard sell language at the end of posts

## 圈层代理信号: 10

Weak proxy only. This never proves follower identity.

Count topic overlap in content/comments with:

- founder、startup、创业、AI、app、SaaS、tech、VC、投资人、融资、独立开发、build in public、留学生

Markdown summaries must label this signal low-confidence and recommend manual review.

## Risk Deduction: up to 20

Deduct for:

- 中介、机构、课程、低价申请、广告、抽奖、互粉、搬运、纯营销、疑似刷量、评论异常

If `risk_deduction >= 15`, force `Reject` regardless of final score.

## Priority

- `A`: score >= 80
- `B`: 65-79
- `C`: 50-64
- `Reject`: score < 50 or `risk_deduction >= 15`
