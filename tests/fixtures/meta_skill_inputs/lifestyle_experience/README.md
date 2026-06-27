# Lifestyle Meta-Skill Experience Fixtures

This directory contains manually usable fixtures for WebUI testing. Use a fresh
session for each scenario to avoid context carryover.

Important: do not paste these prompts into a session that just ran a paper,
LaTeX, PDF export, or failed long workflow. If the WebUI shows an error like
`MANUSCRIPT_TEX block missing`, that is the `meta-paper-write` workflow still
continuing in the old session, not one of these lifestyle fixtures. Start a new
WebUI chat/session and paste one scenario prompt there.

Gateway used during preparation:

- URL: `http://47.254.3.56:18792/control/`
- Token: see the current operator message, not this fixture directory.

## Scenarios

### PDF Intelligence

File:

- `/tmp/opensquilla-meta-skill-pr/tests/fixtures/meta_skill_inputs/pdf_intelligence/router-evaluation-summary.pdf`

Prompt:

```text
帮我看一下这个 PDF：

/tmp/opensquilla-meta-skill-pr/tests/fixtures/meta_skill_inputs/pdf_intelligence/router-evaluation-summary.pdf

我主要想知道：这份报告的核心结论是什么？有哪些证据支持？有没有明显的风险、缺口或需要追问的地方？请用证据表列出来，最后给我一个适合发给团队的简短总结。
```

### Travel Admin Pack

Files:

- `travel_admin_pack/bookings_email.txt`
- `travel_admin_pack/japan_trip_notes.pdf`

Prompt:

```text
我爸妈 6 月去日本 8 天，我今晚想把出行准备理顺。材料在这里：

/tmp/opensquilla-meta-skill-pr/tests/fixtures/meta_skill_inputs/lifestyle_experience/travel_admin_pack/bookings_email.txt
/tmp/opensquilla-meta-skill-pr/tests/fixtures/meta_skill_inputs/lifestyle_experience/travel_admin_pack/japan_trip_notes.pdf

他们不太会折腾手机，主要用微信、地图、翻译和偶尔视频；预算别太高，但稳定比便宜重要。请帮我做一个出行准备包：上网方案怎么选、今晚该下单什么、要教他们哪些操作、出发前检查清单、天气和行李提醒、哪些信息还缺。
```

### Personal Finance Radar

Files:

- `personal_finance_radar/watchlist.xlsx`
- `personal_finance_radar/context.md`

Prompt:

```text
我想做一个下周的投资观察清单，不要直接叫我买卖。材料在这里：

/tmp/opensquilla-meta-skill-pr/tests/fixtures/meta_skill_inputs/lifestyle_experience/personal_finance_radar/watchlist.xlsx
/tmp/opensquilla-meta-skill-pr/tests/fixtures/meta_skill_inputs/lifestyle_experience/personal_finance_radar/context.md

请帮我整理一个研究型雷达：最近需要关注的新闻和催化因素、主要风险、每个标的下周要看什么指标、哪些信息需要我自己再核实、最后给一个表格方便我周一早上快速扫一遍。
```

### Weekly Life Review

File:

- `weekly_life_review/week_notes.md`

Prompt:

```text
帮我做个这周复盘，材料在这里：

/tmp/opensquilla-meta-skill-pr/tests/fixtures/meta_skill_inputs/lifestyle_experience/weekly_life_review/week_notes.md

请给我一个真实一点的复盘：本周完成了什么、卡住在哪里、哪些模式值得保留或停止、下周最重要的 3 个结果、每天可以执行的第一个动作、还有需要记录或提醒自己的事项。
```
