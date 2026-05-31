"""Lifestyle meta-skill benchmark against the OpenClaw t3 baseline.

This catalog is intentionally narrower than ``compare_meta_skill_openclaw``:
it covers retained practical work/life meta-skills and frames each case so the
OpenSquilla meta-skill orchestration path can be judged against OpenClaw's
t3 Opus 4.7 baseline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.compare_meta_skill_openclaw import (
    ComparisonCase,
    EndpointResult,
    JudgeResult,
    LLMJudge,
    OpenClawRunner,
    OpenSquillaRunner,
    RubricCriterion,
    apply_judge_result,
    criterion,
    extract_text_from_events,
    _openclaw_session_file_events,
    read_judge_api_key,
    read_openclaw_token,
    read_opensquilla_token,
    score_response,
)


REPORT_DIR = Path(
    os.environ.get("OPENSQUILLA_LIFESTYLE_COMPARE_REPORT_DIR", ".reports/meta-skill-comparison")
)
OPENCLAW_T3_MODEL = os.environ.get("OPENCLAW_T3_MODEL", "t3-opus-4.7")
OPENCLAW_BASELINE_LABEL = "OpenClaw + t3 + capability-equivalent normal skills baseline"
MATCHED_OPENCLAW_NORMAL_SKILLS = (
    "OpenSquilla multi-search-engine -> OpenClaw multi-search-engine",
    "OpenSquilla docx -> OpenClaw word-docx",
    "OpenSquilla xlsx -> OpenClaw excel-xlsx",
    "OpenSquilla pdf-toolkit -> OpenClaw pdf-toolkit",
    "OpenSquilla deep-research -> OpenClaw deep-research-pro",
    "OpenSquilla weather -> OpenClaw weather",
    "OpenSquilla summarize -> OpenClaw summarize",
    "OpenSquilla memory -> OpenClaw longterm-memory/notes if installed",
    "OpenSquilla pptx -> OpenClaw pptx/presentation skill if installed",
)
BENCHMARK_LABEL = f"OpenSquilla + Squilla Router vs {OPENCLAW_BASELINE_LABEL}"
LIFESTYLE_JUDGE_SUBSCORE_RANGES: dict[str, tuple[int, int]] = {
    "final_artifact_quality": (0, 40),
    "task_completion": (0, 20),
    "evidence_traceability": (0, 15),
    "actionability": (0, 10),
    "risk_boundary_safety": (0, 10),
    "meta_skill_fit": (0, 5),
}


DOCUMENT_DECISION_RUBRIC: tuple[RubricCriterion, ...] = (
    criterion("bottom_line", "Gives a clear sign/negotiate/reject recommendation.", r"recommendation", r"建议", r"bottom[- ]line"),
    criterion("evidence_table", "Uses an evidence table or source-by-source facts.", r"evidence table", r"证据表", r"source", r"来源"),
    criterion("money_dates_obligations", "Extracts money, dates, penalties, renewal, or obligations.", r"18,?600", r"2026-06-0[23]", r"renew", r"续约", r"penalt", r"违约"),
    criterion("risk_ranking", "Ranks risks by severity.", r"high", r"medium", r"low", r"高", r"中", r"低"),
    criterion("next_24h", "Provides actions for the next 24 hours.", r"24 hours", r"24 小时", r"next step", r"下一步"),
    criterion("professional_caveat", "Flags legal/accounting review instead of giving regulated advice.", r"lawyer", r"legal", r"律师", r"professional"),
)

WEB_PARENT_ESIM_RUBRIC: tuple[RubricCriterion, ...] = (
    criterion("decision_context", "States assumptions and the parent's travel context.", r"assumption", r"假设", r"decision context", r"爸妈", r"parents"),
    criterion("clear_recommendation", "Chooses eSIM, roaming, local SIM, or hybrid.", r"recommendation", r"建议", r"eSIM", r"roaming", r"漫游"),
    criterion("source_list", "Includes source list with URLs or source IDs.", r"https?://", r"\[S\d+\]", r"Sources", r"来源"),
    criterion("tradeoffs", "Compares activation, support, hotspot, refund, or phone compatibility.", r"activation", r"激活", r"hotspot", r"客服", r"refund", r"兼容"),
    criterion("next_steps", "Provides purchase/setup/checklist steps.", r"next step", r"下一步", r"checklist", r"清单"),
    criterion("evidence_limits", "Separates current evidence limits from recommendations.", r"evidence limit", r"限制", r"unknown", r"无法确认"),
)

DAILY_OPERATOR_RUBRIC: tuple[RubricCriterion, ...] = (
    criterion("top_priorities", "Returns the top three priorities.", r"top 3", r"前三", r"priority", r"优先"),
    criterion("time_blocks", "Creates concrete time blocks.", r"\b0?[89]:\d\d", r"\b1[0-8]:\d\d", r"time block", r"时间块"),
    criterion("calendar_risks", "Calls out schedule conflicts or task risks.", r"risk", r"冲突", r"delay", r"延期"),
    criterion("weather_commute", "Accounts for weather or commute implications.", r"weather", r"天气", r"commute", r"通勤", r"雨"),
    criterion("followups", "Names people/messages to follow up.", r"follow up", r"跟进", r"提醒", r"message"),
    criterion("data_limits", "States connector/data limits.", r"missing connector", r"数据限制", r"only pasted", r"仅根据"),
)

COMPETITIVE_INTEL_RUBRIC: tuple[RubricCriterion, ...] = (
    criterion("target_scope", "Names the monitored targets and requested dimensions.", r"ByteDance", r"小红书", r"账号", r"账户", r"dimension", r"维度"),
    criterion("signal_table", "Creates a signal table or structured account-by-dimension list.", r"signal", r"信号", r"table", r"表", r"pricing", r"产品", r"hiring", r"招聘"),
    criterion("baseline_diff", "Separates new/changed/unchanged signals against the pasted baseline.", r"new", r"changed", r"unchanged", r"新增", r"变化", r"基线"),
    criterion("strength_verdict", "Classifies signal strength or urgency.", r"URGENT", r"HIGH", r"MED", r"LOW", r"紧急", r"高", r"中", r"低"),
    criterion("next_actions", "Gives concrete sales/BD/competitive next actions.", r"next action", r"下一步", r"follow up", r"跟进", r"老板"),
    criterion("source_limits", "Labels source limits and avoids inventing unsourced facts.", r"source", r"来源", r"unknown", r"未验证", r"仅根据"),
)

JOB_SEARCH_RUBRIC: tuple[RubricCriterion, ...] = (
    criterion("role_company_fit", "Identifies the target role/company and fit thesis.", r"product operations", r"运营", r"role", r"岗位", r"fit", r"匹配"),
    criterion("tailored_resume", "Produces tailored resume bullets without inventing experience.", r"简历", r"resume", r"bullet", r"项目", r"指标", r"rephrased"),
    criterion("cover_letter", "Includes a concise cover letter or outreach note.", r"cover letter", r"求职信", r"邮件", r"outreach", r"开头"),
    criterion("jd_gap_table", "Maps JD requirements to evidence and gaps.", r"JD", r"requirements", r"gap", r"差距", r"证据", r"要求"),
    criterion("interview_prep", "Adds interview prep or likely questions when useful.", r"interview", r"面试", r"question", r"准备"),
    criterion("truth_safety", "States no fabrication and marks unverifiable or missing facts.", r"do not invent", r"不编", r"未提供", r"unknown", r"真实"),
)

KID_PROJECT_RUBRIC: tuple[RubricCriterion, ...] = (
    criterion("age_fit", "Adapts the plan to child age and guardian involvement.", r"8 岁", r"age", r"年龄", r"家长", r"guardian"),
    criterion("step_plan", "Creates a clear day-by-day or session-by-session plan.", r"Day", r"第", r"步骤", r"step", r"timeline", r"时间表"),
    criterion("materials_budget", "Lists materials, budget, and household substitutes.", r"materials", r"材料", r"预算", r"substitute", r"替代"),
    criterion("safety", "Flags safety hazards and supervision requirements.", r"safety", r"安全", r"supervision", r"监督", r"adult", r"大人"),
    criterion("learning_objectives", "Explains what the child should learn and present.", r"learn", r"学习", r"原理", r"presentation", r"展示"),
    criterion("weather_or_constraints", "Handles outdoor/weather/deadline constraints and assumptions.", r"weather", r"天气", r"deadline", r"截止", r"assumption", r"假设"),
)


LIFESTYLE_COMPARISON_CASES: list[ComparisonCase] = [
    ComparisonCase(
        case_id="document_vendor_decision",
        skill_name="meta-document-to-decision",
        scenario="lifestyle_primary",
        prompt=(
            "帮我看一下这个供应商续费材料，我明天要决定要不要签。"
            "材料是我复制出来的：报价单 A 写着年度服务费 18,600 元，"
            "付款期限 2026-06-03，包含 20 个账号；合同摘录写着自动续约 12 个月，"
            "提前 30 天书面取消，否则收 30% 违约金；邮件里销售又说“可以随时停”。"
            "请给我一个能直接转发给老板的决策简报：建议签/不签/先谈，证据表，"
            "高中低风险，要问供应商的问题，接下来 24 小时怎么做。"
        ),
        expected_advantage=(
            "OpenSquilla + Squilla Router should activate document-to-decision, "
            "extract money/date/obligation evidence, and beat the OpenClaw + t3 "
            "Opus 4.7 generic answer on traceable decision readiness."
        ),
        optimization_if_not_better=(
            "If OpenSquilla does not beat OpenClaw, tighten the document fallback "
            "so pasted quotes/contracts always produce an evidence table, risk "
            "ranking, and next-24-hour action list."
        ),
        rubric=DOCUMENT_DECISION_RUBRIC,
        failure_modes=(
            "Gives a generic business answer without quoting the money/date/renewal facts.",
            "Misses the conflict between 'auto-renewal' and 'can stop anytime'.",
            "Does not separate decision recommendation from legal/accounting caveats.",
        ),
    ),
    ComparisonCase(
        case_id="web_research_parent_esim",
        skill_name="meta-web-research-to-report",
        scenario="lifestyle_primary",
        prompt=(
            "爸妈 6 月去日本 8 天，我想今天帮他们定上网方案。"
            "他们不太会折腾手机，主要用微信、地图、翻译和偶尔视频，预算别太高。"
            "你帮我查一下并写个简短决策 memo：买旅游 eSIM、开运营商漫游、"
            "还是到当地买卡哪个更稳？要有来源、关键发现、风险取舍、"
            "我今晚该怎么下单和教他们怎么用。"
        ),
        expected_advantage=(
            "OpenSquilla + Squilla Router should activate web-research-to-report, "
            "curate current sources, map claims to evidence, and beat the OpenClaw "
            "+ t3 Opus 4.7 baseline on sourced decision support."
        ),
        optimization_if_not_better=(
            "If OpenSquilla does not beat OpenClaw, strengthen quick decision memo "
            "mode to require source-to-claim mapping, evidence limits, and a setup "
            "checklist for non-technical users."
        ),
        rubric=WEB_PARENT_ESIM_RUBRIC,
        failure_modes=(
            "Provides current-looking telecom claims without sources.",
            "Does not account for non-technical parents and activation risk.",
            "Gives no concrete purchase/setup checklist.",
        ),
    ),
    ComparisonCase(
        case_id="daily_operator_morning_plan",
        skill_name="meta-daily-operator-brief",
        scenario="lifestyle_primary",
        prompt=(
            "今天先帮我排一下。我在上海，下午 15:00 有客户 demo，"
            "11:30 要回财务的报销问题，18:30 和朋友吃饭；"
            "昨天老板让我今天把 router 评测表补完，孩子老师昨天 16:20 发消息说要确认明天活动人数。"
            "我还有两封邮件没回：李总问报价、HR 问面试时间。"
            "请给我一个早上能照着做的今日简报：前三优先级、时间块、风险、天气/通勤影响、"
            "该跟进谁、哪些数据是你没法直接读取只能根据我贴的内容判断。"
        ),
        expected_advantage=(
            "OpenSquilla + Squilla Router should activate daily-operator-brief, "
            "combine pasted calendar/task context with weather/memory-aware planning, "
            "and beat OpenClaw + t3 Opus 4.7 on executable daily operations."
        ),
        optimization_if_not_better=(
            "If OpenSquilla does not beat OpenClaw, make the final brief enforce "
            "top-3 priorities, explicit time blocks, follow-up names, and missing "
            "connector limits."
        ),
        rubric=DAILY_OPERATOR_RUBRIC,
        failure_modes=(
            "Lists tasks without prioritizing the demo, reimbursement, and router table.",
            "Omits fixed times or creates an impossible schedule.",
            "Claims live calendar/email/weather access without evidence.",
        ),
    ),
    ComparisonCase(
        case_id="competitive_intel_competitor_week",
        skill_name="meta-competitive-intel",
        scenario="lifestyle_primary",
        prompt=(
            "帮我盯一下这两个对手最近有没有值得提醒老板的动作：小红书和得物。"
            "我们做的是年轻人消费社区，上次我给老板的基线是：小红书重点在商业化和本地生活，"
            "得物重点在潮流电商和鉴定服务；上次没看到明显降价，也没看到高管变化。"
            "这次我主要关心最近一个月的产品、价格/活动、招聘、合作和融资新闻。"
            "请给我一份能发到销售群里的简报：先说有没有新信号，再给账户 x 维度表，"
            "哪些和基线相比有变化，信号强度，高中低优先级，今天该跟进谁。"
        ),
        expected_advantage=(
            "OpenSquilla + Squilla Router should activate competitive-intel, combine "
            "multi-search, summarization, memory/baseline diff, and optional export "
            "logic, then beat OpenClaw + t3 Opus 4.7 on grounded competitive signal "
            "triage and next actions."
        ),
        optimization_if_not_better=(
            "If OpenSquilla does not beat OpenClaw, strengthen competitive-intel so pasted "
            "baselines always produce an explicit new/changed/unchanged section, "
            "signal-strength labels, and concrete sales/BD follow-ups."
        ),
        rubric=COMPETITIVE_INTEL_RUBRIC,
        failure_modes=(
            "Gives a generic competitor overview without account-by-dimension signals.",
            "Fails to diff against the pasted baseline.",
            "Invents leadership, funding, or pricing facts without source limits.",
        ),
    ),
    ComparisonCase(
        case_id="job_search_tailor_pack",
        skill_name="meta-job-search-pipeline",
        scenario="lifestyle_primary",
        prompt=(
            "我想投一个产品运营岗位，帮我把材料整理成能直接改简历和发邮件的版本。"
            "JD 摘要：一家 B2B SaaS 公司招产品运营，要求会看数据、写用户调研、推动跨部门上线，"
            "最好懂 AI 工具；工作内容包括做用户反馈闭环、整理需求优先级、写上线说明、跟销售和客服对齐。"
            "我的简历片段：做过 2 年运营，负责过 3 个企业客户的上线培训；用 SQL 做过留存报表，"
            "把新手引导完成率从 52% 提到 68%；写过 20 多篇帮助文档；最近参与过一个 AI 客服试点，"
            "但不是负责人。请输出：简历改写要点、可直接粘贴的中文简历段落、求职信、JD 要求-我的证据-缺口表、"
            "面试前两天怎么准备。不要替我编没有做过的经历。"
        ),
        expected_advantage=(
            "OpenSquilla + Squilla Router should activate job-search-pipeline, tailor "
            "the resume and cover letter from pasted JD/resume evidence, add company "
            "research when available, and beat OpenClaw + t3 Opus 4.7 on truthful, "
            "send-ready application quality."
        ),
        optimization_if_not_better=(
            "If OpenSquilla does not beat OpenClaw, make job-search-pipeline enforce "
            "JD-to-evidence mapping, no-fabrication language, concrete rewritten "
            "bullets, and a short interview-prep plan."
        ),
        rubric=JOB_SEARCH_RUBRIC,
        failure_modes=(
            "Writes generic career advice instead of tailored resume and outreach text.",
            "Fabricates ownership or metrics not present in the resume snippet.",
            "Omits the JD requirement/evidence/gap mapping.",
        ),
    ),
    ComparisonCase(
        case_id="kid_project_balcony_plants",
        skill_name="meta-kid-project-planner",
        scenario="lifestyle_primary",
        prompt=(
            "孩子 8 岁，科学课两周后要交一个小项目。她想做“阳台种豆芽/小植物观察”，"
            "家里有透明杯、纸巾、绿豆、尺子和彩笔，预算最好 50 元以内。我们住杭州，"
            "阳台有半天太阳，平时我只能晚上陪 20 分钟。请帮我做一个孩子能看懂、家长也能执行的计划："
            "每天做什么、材料清单和替代品、安全注意、怎么记录数据和画图、最后展示怎么讲，"
            "如果天气或光照不稳定要怎么调整，哪些地方你只能先假设。"
        ),
        expected_advantage=(
            "OpenSquilla + Squilla Router should activate kid-project-planner, combine "
            "age fit, materials, weather-aware constraints, safety review, and parent "
            "learning objectives, then beat OpenClaw + t3 Opus 4.7 on an executable "
            "child-and-guardian project plan."
        ),
        optimization_if_not_better=(
            "If OpenSquilla does not beat OpenClaw, strengthen kid-project-planner to "
            "always produce kid-facing steps, guardian notes, material substitutes, "
            "safety checks, data-recording templates, and assumption labels."
        ),
        rubric=KID_PROJECT_RUBRIC,
        failure_modes=(
            "Gives a generic plant project answer without adapting to an 8-year-old.",
            "Misses the 50 RMB budget, nightly 20-minute supervision, or light/weather constraints.",
            "Omits safety, data recording, or presentation guidance.",
        ),
    ),
]


ENGLISH_LIFESTYLE_PROMPTS: dict[str, str] = {
    "document_vendor_decision": (
        "Can you help me review these vendor renewal materials? I need to decide tomorrow "
        "whether to sign. I copied the key parts here: Quote A says the annual service fee "
        "is RMB 18,600, payment is due on 2026-06-03, and it includes 20 seats. The contract "
        "excerpt says it auto-renews for 12 months and requires written cancellation 30 days "
        "in advance, otherwise there is a 30% penalty. But the sales email says we can "
        "\"stop anytime.\" Please give me a decision brief I can forward to my boss: sign, "
        "reject, or negotiate first; an evidence table; high/medium/low risks; questions "
        "for the vendor; and what to do in the next 24 hours."
    ),
    "web_research_parent_esim": (
        "My parents are going to Japan for 8 days in June, and I want to sort out their "
        "mobile data plan today. They are not very comfortable changing phone settings. "
        "They mainly need WeChat, maps, translation, and occasional video calls, and I do "
        "not want to overspend. Please help me compare a travel eSIM, carrier roaming, and "
        "buying a local SIM after landing. I need a short decision memo with sources, key "
        "findings, tradeoffs and risks, and exactly what I should order and teach them "
        "tonight."
    ),
    "daily_operator_morning_plan": (
        "Please help me plan today. I am in Shanghai. I have a customer demo at 15:00, "
        "a reimbursement question from finance due by 11:30, and dinner with a friend at "
        "18:30. Yesterday my boss asked me to finish the router evaluation sheet today. "
        "My child's teacher messaged yesterday at 16:20 asking us to confirm tomorrow's activity "
        "headcount. I also have two emails to answer: Mr. Li asked about a quote, and HR "
        "asked about interview timing. Please give me a morning brief I can follow: top "
        "three priorities, time blocks, risks, weather/commute implications, who to follow "
        "up with, and what you cannot directly read and can only infer from what I pasted."
    ),
    "competitive_intel_competitor_week": (
        "Please help me keep an eye on two competitors and tell me whether anything is worth "
        "flagging to my boss: Xiaohongshu and Dewu. We build a youth consumer community. "
        "The baseline I gave my boss last time was: Xiaohongshu seemed focused on monetization "
        "and local services, Dewu seemed focused on fashion ecommerce and authentication services; "
        "I did not see obvious price cuts or leadership changes. This time I care about product, "
        "pricing or campaigns, hiring, partnerships, and funding/news over the past month. Please "
        "give me a brief I can post in the sales group: whether there are new signals, an account "
        "by dimension table, what changed from the baseline, signal strength, high/medium/low "
        "priorities, and who to follow up with today."
    ),
    "job_search_tailor_pack": (
        "I want to apply for a product operations role. Please turn my materials into something "
        "I can use to revise my resume and send an email. JD summary: a B2B SaaS company is hiring "
        "for product operations; they want data analysis, user research writing, cross-functional "
        "launch coordination, and ideally AI tooling experience. The job includes closing user "
        "feedback loops, prioritizing requirements, writing release notes, and aligning with sales "
        "and support. My resume snippet: 2 years in operations; owned onboarding training for "
        "3 enterprise customers; used SQL for retention reporting; raised new-user guide completion "
        "from 52% to 68%; wrote 20+ help docs; recently joined an AI customer-service pilot but was "
        "not the owner. Please output resume-rewrite points, Chinese resume text I can paste, a cover "
        "letter, a JD requirement / my evidence / gap table, and a two-day interview prep plan. Do "
        "not invent experience I do not have."
    ),
    "kid_project_balcony_plants": (
        "My child is 8 and needs to submit a small science project in two weeks. She wants to do "
        "a balcony sprout or small-plant observation project. At home we have clear cups, paper "
        "towels, mung beans, a ruler, and colored pens, and I want to keep the budget under RMB 50. "
        "We live in Hangzhou, the balcony gets half a day of sun, and I can only help for 20 minutes "
        "in the evening. Please make a plan that a child can understand and a parent can actually "
        "supervise: what to do each day, materials and substitutes, safety notes, how to record data "
        "and draw charts, how to present the final result, how to adjust if weather or light is "
        "unstable, and what you have to assume."
    ),
}


def _placeholder_result(endpoint: str, case: ComparisonCase) -> EndpointResult:
    return EndpointResult(
        endpoint=endpoint,
        case_id=case.case_id,
        ok=False,
        elapsed_s=0.0,
        response_text="",
        score=asdict(score_response("", case)),
        error="not run",
        model=OPENCLAW_T3_MODEL if endpoint == "openclaw" else None,
    )


def build_lifestyle_rows(language: str = "zh") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in _cases_for_language(language):
        rows.append(
            {
                "case": _case_to_dict(case),
                "benchmark": BENCHMARK_LABEL,
                "opensquilla": asdict(_placeholder_result("opensquilla", case)),
                "openclaw": asdict(_placeholder_result("openclaw", case)),
                "baseline_model": OPENCLAW_T3_MODEL,
                "baseline_winner": "tie",
                "winner": "tie",
                "score_basis": "not_run",
                "opensquilla_better": False,
                "recommended_optimization": case.optimization_if_not_better,
            }
        )
    return rows


def render_lifestyle_markdown(rows: list[dict[str, Any]]) -> str:
    total = len(rows)
    sq_wins = sum(1 for row in rows if row["winner"] == "opensquilla")
    claw_wins = sum(1 for row in rows if row["winner"] == "openclaw")
    ties = sum(1 for row in rows if row["winner"] == "tie")
    lines = [
        "# OpenSquilla Meta-Skills vs OpenClaw t3 Matched-Skills Lifestyle Benchmark",
        "",
        f"Benchmark: {BENCHMARK_LABEL}",
        f"{OPENCLAW_BASELINE_LABEL} model: `{OPENCLAW_T3_MODEL}`",
        "Matched OpenClaw normal skills: "
        + ", ".join(f"`{skill}`" for skill in MATCHED_OPENCLAW_NORMAL_SKILLS),
        "",
        "## Summary",
        "",
        f"OpenSquilla + Squilla Router wins: {sq_wins}/{total}; {OPENCLAW_BASELINE_LABEL} wins: {claw_wins}/{total}; ties/not-run: {ties}.",
        "",
        "| Case | Meta-skill | OpenSquilla model | OpenClaw model | Deterministic | Judge 0-100 | Final artifact | Basis | Winner | Issue |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {case} | `{skill}` | `{sq_model}` | `{claw_model}` | {det} | {judge} | {artifact} | {basis} | {winner} | {issue} |".format(
                case=row["case"]["case_id"],
                skill=row["case"]["skill_name"],
                sq_model=row["opensquilla"].get("model") or "",
                claw_model=row["openclaw"].get("model") or "",
                det=f"{row['opensquilla']['score']['total']}-{row['openclaw']['score']['total']}",
                judge=_judge_scores_cell(row),
                artifact=_judge_final_artifact_cell(row),
                basis=row.get("score_basis", ""),
                winner=row["winner"],
                issue=_judge_issue_cell(row).replace("|", "/"),
            )
        )
    lines.extend(["", "## Cases", ""])
    for row in rows:
        case = row["case"]
        lines.append(f"### {case['case_id']}")
        lines.append("")
        lines.append(f"- Meta-skill: `{case['skill_name']}`")
        lines.append(f"- Scenario: {case['scenario']}")
        lines.append(f"- Expected advantage: {case['expected_advantage']}")
        lines.append(f"- Baseline: {OPENCLAW_BASELINE_LABEL} (`{OPENCLAW_T3_MODEL}`)")
        lines.append("- Rubric: " + ", ".join(item["name"] for item in case["rubric"]))
        lines.append("- Failure modes: " + "; ".join(case["failure_modes"]))
        lines.append("")
        lines.append("```text")
        lines.append(case["prompt"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def render_lifestyle_prompts_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Lifestyle Test Prompts",
        "",
    ]
    for row in rows:
        case = row["case"]
        lines.append(f"## {case['case_id']}")
        lines.append("")
        lines.append("### 中文")
        lines.append("")
        lines.append("```text")
        original = next(
            item for item in LIFESTYLE_COMPARISON_CASES if item.case_id == case["case_id"].removesuffix("_en")
        )
        lines.append(original.prompt)
        lines.append("```")
        lines.append("")
        lines.append("### English")
        lines.append("")
        lines.append("```text")
        lines.append(ENGLISH_LIFESTYLE_PROMPTS[original.case_id])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _judge_scores_cell(row: dict[str, Any]) -> str:
    judge = row.get("judge") if isinstance(row.get("judge"), dict) else {}
    scores = judge.get("scores") if isinstance(judge.get("scores"), dict) else {}
    if not scores:
        return ""
    return f"{scores.get('opensquilla', '')}-{scores.get('openclaw', '')}"


def _judge_final_artifact_cell(row: dict[str, Any]) -> str:
    judge = row.get("judge") if isinstance(row.get("judge"), dict) else {}
    raw = judge.get("raw") if isinstance(judge.get("raw"), dict) else {}
    subscores = raw.get("subscores") if isinstance(raw.get("subscores"), dict) else {}
    opensquilla = subscores.get("opensquilla") if isinstance(subscores.get("opensquilla"), dict) else {}
    openclaw = subscores.get("openclaw") if isinstance(subscores.get("openclaw"), dict) else {}
    if not opensquilla and not openclaw:
        return ""
    return f"{opensquilla.get('final_artifact_quality', '')}-{openclaw.get('final_artifact_quality', '')}"


def _judge_issue_cell(row: dict[str, Any]) -> str:
    if row.get("invalid_reasons"):
        return "; ".join(str(item) for item in row["invalid_reasons"])
    if row.get("judge_error"):
        return str(row["judge_error"])
    judge = row.get("judge") if isinstance(row.get("judge"), dict) else {}
    if row.get("score_basis") == "llm_judge":
        raw = judge.get("raw") if isinstance(judge.get("raw"), dict) else {}
        if not judge.get("scores") or not raw.get("subscores") or not judge.get("rationale"):
            return "incomplete_judge_payload"
    return ""


def write_lifestyle_reports(rows: list[dict[str, Any]], stamp: str | None = None) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if stamp is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jsonl_path = REPORT_DIR / f"openclaw_t3_vs_opensquilla_lifestyle_meta_{stamp}.jsonl"
    md_path = REPORT_DIR / f"openclaw_t3_vs_opensquilla_lifestyle_meta_{stamp}.md"
    prompts_path = REPORT_DIR / f"openclaw_t3_vs_opensquilla_lifestyle_meta_prompts_{stamp}.md"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    md_path.write_text(render_lifestyle_markdown(rows), encoding="utf-8")
    prompts_path.write_text(render_lifestyle_prompts_markdown(rows), encoding="utf-8")
    print(f"wrote {jsonl_path}")
    print(f"wrote {md_path}")
    print(f"wrote {prompts_path}")
    return jsonl_path, md_path


async def run_live(args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = _select_cases(args.case, language=args.prompt_language)
    if not args.openclaw_config and not args.openclaw_baseline_jsonl:
        raise SystemExit("Pass --openclaw-config or set OPENCLAW_CONFIG.")
    opensquilla = OpenSquillaRunner(
        args.opensquilla_url,
        args.opensquilla_token,
        elevated=args.opensquilla_elevated,
        agent_id=args.opensquilla_agent_id,
        isolated_agent_per_case=args.opensquilla_isolated_agents,
        run_id=args.opensquilla_run_id,
    )
    openclaw = None
    openclaw_baseline = {}
    openclaw_state_dir = Path(args.openclaw_config).parent if args.openclaw_config else None
    if args.openclaw_baseline_jsonl:
        openclaw_baseline = load_openclaw_baseline(
            Path(args.openclaw_baseline_jsonl),
            selected,
            state_dir=openclaw_state_dir,
        )
    else:
        openclaw = OpenClawRunner(
            args.openclaw_url,
            read_openclaw_token(Path(args.openclaw_config)),
            args.openclaw_idle_timeout,
            state_dir=openclaw_state_dir,
        )
    judge = None
    if args.judge_llm:
        if not args.judge_model:
            raise SystemExit("Pass --judge-model or set OPENSQUILLA_JUDGE_MODEL.")
        judge = LLMJudge(
            model=args.judge_model,
            api_key=args.judge_api_key,
            base_url=args.judge_base_url,
            timeout_s=args.judge_timeout,
        )

    rows: list[dict[str, Any]] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for case in selected:
        print(f"running {case.case_id} ...", flush=True)
        if openclaw_baseline:
            sq_result = await opensquilla.run(case, args.timeout)
            claw_result = openclaw_baseline[case.case_id]
        else:
            assert openclaw is not None
            sq_result, claw_result = await asyncio.gather(
                opensquilla.run(case, args.timeout),
                openclaw.run(case, args.timeout),
            )
        if not claw_result.model:
            claw_result.model = OPENCLAW_T3_MODEL
        row = _compare_results(case, sq_result, claw_result)
        if judge is not None and row.get("score_basis") != "invalid_endpoint":
            try:
                judge_result = await _judge_lifestyle_with_retries(
                    judge,
                    case,
                    sq_result,
                    claw_result,
                )
                row = _apply_lifestyle_judge_result(row, judge_result, case)
            except Exception as exc:
                row["judge_error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        judge_suffix = ""
        if row.get("judge"):
            judge_suffix = (
                f" judge={_judge_scores_cell(row) or 'n/a'}"
                f" final_artifact={_judge_final_artifact_cell(row) or 'n/a'}"
            )
        elif row.get("judge_error"):
            judge_suffix = f" judge_error={row['judge_error']}"
        print(
            f"{case.case_id}: opensquilla={sq_result.score['total']} "
            f"openclaw_t3={claw_result.score['total']}{judge_suffix} "
            f"opensquilla_model={sq_result.model or ''} "
            f"openclaw_model={claw_result.model or OPENCLAW_T3_MODEL} "
            f"winner={row['winner']}",
            flush=True,
        )
        write_lifestyle_reports(rows, stamp=stamp)
    write_lifestyle_reports(rows, stamp=stamp)
    return rows


async def judge_existing(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not args.judge_jsonl:
        raise SystemExit("Pass --judge-jsonl.")
    if not args.judge_model:
        raise SystemExit("Pass --judge-model or set OPENSQUILLA_JUDGE_MODEL.")
    judge = LLMJudge(
        model=args.judge_model,
        api_key=args.judge_api_key,
        base_url=args.judge_base_url,
        timeout_s=args.judge_timeout,
    )
    rows = [
        json.loads(line)
        for line in Path(args.judge_jsonl).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    judged_rows: list[dict[str, Any]] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for row in rows:
        case = _case_from_dict(row["case"])
        opensquilla = _endpoint_from_dict(row["opensquilla"])
        openclaw = _endpoint_from_dict(row["openclaw"])
        row.setdefault("baseline_winner", row.get("winner", "tie"))
        row.setdefault("score_basis", "deterministic")
        try:
            judge_result = await _judge_lifestyle_with_retries(
                judge,
                case,
                opensquilla,
                openclaw,
            )
            judged = _apply_lifestyle_judge_result(row, judge_result, case)
        except Exception as exc:
            judged = dict(row)
            judged["judge_error"] = f"{type(exc).__name__}: {exc}"
        judged_rows.append(judged)
        print(
            f"judged {case.case_id}: winner={judged.get('winner')} "
            f"judge={_judge_scores_cell(judged) or 'n/a'}",
            flush=True,
        )
        write_lifestyle_reports(judged_rows, stamp=stamp)
    write_lifestyle_reports(judged_rows, stamp=stamp)
    return judged_rows


def load_openclaw_baseline(
    path: Path,
    cases: list[ComparisonCase],
    *,
    state_dir: Path | None = None,
) -> dict[str, EndpointResult]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_case = {str(row["case"]["case_id"]): row for row in rows}
    baseline: dict[str, EndpointResult] = {}
    for case in cases:
        row = by_case.get(case.case_id)
        if row is None:
            raise SystemExit(f"OpenClaw baseline missing case {case.case_id!r} in {path}")
        baseline_prompt = str(row.get("case", {}).get("prompt", ""))
        if baseline_prompt != case.prompt:
            raise SystemExit(
                f"OpenClaw baseline prompt mismatch for {case.case_id!r}; "
                "use the exact prompt that produced the locked baseline"
            )
        result = _endpoint_from_dict(row["openclaw"])
        refreshed = _refreshed_openclaw_text_from_state(
            result.session_key,
            case.prompt,
            state_dir,
        )
        if refreshed and len(refreshed) > len(result.response_text.strip()):
            result.response_text = refreshed
            result.ok = True
            result.error = None
            result.score = asdict(score_response(refreshed, case))
        if not result.model:
            result.model = OPENCLAW_T3_MODEL
        baseline[case.case_id] = result
    return baseline


def _endpoint_from_dict(data: dict[str, Any]) -> EndpointResult:
    return EndpointResult(
        endpoint=str(data.get("endpoint", "openclaw")),
        case_id=str(data["case_id"]),
        ok=bool(data.get("ok")),
        elapsed_s=float(data.get("elapsed_s", 0.0)),
        response_text=str(data.get("response_text", "")),
        score=data.get("score") if isinstance(data.get("score"), dict) else {},
        error=str(data["error"]) if data.get("error") else None,
        session_key=str(data["session_key"]) if data.get("session_key") else None,
        model=str(data["model"]) if data.get("model") else None,
        provider=str(data["provider"]) if data.get("provider") else None,
        event_count=int(data.get("event_count", 0)),
    )


def _refreshed_openclaw_text_from_state(
    session_key: str | None,
    prompt: str,
    state_dir: Path | None,
) -> str:
    path = _openclaw_session_file_for_key(state_dir, session_key)
    if path is None:
        return ""
    return extract_text_from_events(
        _openclaw_session_file_events(path, session_key or "", after_prompt=prompt)
    )


def _openclaw_session_file_for_key(
    state_dir: Path | None,
    session_key: str | None,
) -> Path | None:
    if state_dir is None or not session_key:
        return None
    sessions_dir = state_dir / "agents" / "main" / "sessions"
    if not sessions_dir.exists():
        return None
    for trajectory_path in sessions_dir.glob("*.trajectory.jsonl"):
        try:
            text = trajectory_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if session_key not in text:
            continue
        session_file = trajectory_path.with_name(
            trajectory_path.name.replace(".trajectory.jsonl", ".jsonl")
        )
        if session_file.exists():
            return session_file
    return None


def _compare_results(
    case: ComparisonCase,
    opensquilla: EndpointResult,
    openclaw: EndpointResult,
) -> dict[str, Any]:
    invalid_reasons = _invalid_endpoint_reasons(opensquilla, openclaw)
    if invalid_reasons:
        return {
            "case": _case_to_dict(case),
            "benchmark": BENCHMARK_LABEL,
            "opensquilla": asdict(opensquilla),
            "openclaw": asdict(openclaw),
            "baseline_model": openclaw.model or OPENCLAW_T3_MODEL,
            "baseline_winner": "invalid",
            "winner": "invalid",
            "score_basis": "invalid_endpoint",
            "opensquilla_better": False,
            "invalid_reasons": invalid_reasons,
            "recommended_optimization": None,
        }
    sq_total = int(opensquilla.score["total"])
    claw_total = int(openclaw.score["total"])
    if sq_total > claw_total:
        winner = "opensquilla"
    elif claw_total > sq_total:
        winner = "openclaw"
    else:
        winner = "tie"
    return {
        "case": _case_to_dict(case),
        "benchmark": BENCHMARK_LABEL,
        "opensquilla": asdict(opensquilla),
        "openclaw": asdict(openclaw),
        "baseline_model": openclaw.model or OPENCLAW_T3_MODEL,
        "baseline_winner": winner,
        "winner": winner,
        "score_basis": "deterministic",
        "opensquilla_better": winner == "opensquilla",
        "recommended_optimization": None
        if winner == "opensquilla"
        else case.optimization_if_not_better,
    }


def _invalid_endpoint_reasons(*results: EndpointResult) -> list[str]:
    reasons: list[str] = []
    for result in results:
        if not result.ok:
            reasons.append(f"{result.endpoint}: not ok")
        if not result.response_text.strip():
            reasons.append(f"{result.endpoint}: empty response")
        if _looks_like_unrelated_bootstrap(result.response_text):
            reasons.append(f"{result.endpoint}: unrelated bootstrap response")
        if result.error:
            reasons.append(f"{result.endpoint}: {result.error}")
    return reasons


def _looks_like_unrelated_bootstrap(text: str) -> bool:
    lowered = text.lower()
    bootstrap_phrases = (
        "bootstrap removed",
        "ready for the task",
        "what would you like me to do",
        "who am i",
        "what should they call you",
    )
    return len(text.strip()) < 500 and any(phrase in lowered for phrase in bootstrap_phrases)


def _apply_lifestyle_judge_result(
    row: dict[str, Any],
    judge_result: JudgeResult,
    case: ComparisonCase,
) -> dict[str, Any]:
    normalized = _normalized_lifestyle_judge_result(judge_result)
    if normalized is None:
        raise RuntimeError("judge response missing required scores, subscores, or rationale")
    updated = apply_judge_result(row, normalized, case)
    updated["benchmark"] = BENCHMARK_LABEL
    updated["baseline_model"] = row.get("baseline_model") or OPENCLAW_T3_MODEL
    return updated


async def _judge_lifestyle_with_retries(
    judge: LLMJudge,
    case: ComparisonCase,
    opensquilla: EndpointResult,
    openclaw: EndpointResult,
    *,
    attempts: int = 3,
) -> JudgeResult:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            result = await judge.judge(case, opensquilla, openclaw)
        except Exception as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            continue
        normalized = _normalized_lifestyle_judge_result(result)
        if normalized is not None:
            return normalized
        errors.append(f"attempt {attempt}: incomplete weighted judge payload")
    raise RuntimeError("; ".join(errors))


def _lifestyle_judge_result_is_complete(judge_result: JudgeResult) -> bool:
    return _normalized_lifestyle_judge_result(judge_result) is not None


def _normalized_lifestyle_judge_result(judge_result: JudgeResult) -> JudgeResult | None:
    if not judge_result.rationale.strip():
        return None
    raw = judge_result.raw if isinstance(judge_result.raw, dict) else {}
    totals = _lifestyle_weighted_totals(raw)
    if totals is None:
        return None
    winner = "tie"
    if totals["opensquilla"] > totals["openclaw"]:
        winner = "opensquilla"
    elif totals["openclaw"] > totals["opensquilla"]:
        winner = "openclaw"
    normalized_raw = dict(raw)
    normalized_raw["scores"] = totals
    normalized_raw["winner"] = winner
    normalized_raw["score_source"] = "weighted_subscores"
    return JudgeResult(
        winner=winner,
        scores=totals,
        confidence=judge_result.confidence,
        rationale=judge_result.rationale,
        risks=judge_result.risks,
        raw=normalized_raw,
        model=judge_result.model,
    )


def _lifestyle_weighted_totals(raw: dict[str, Any]) -> dict[str, int] | None:
    subscores = raw.get("subscores") if isinstance(raw.get("subscores"), dict) else {}
    totals: dict[str, int] = {}
    for label in ("opensquilla", "openclaw"):
        candidate = subscores.get(label)
        if not isinstance(candidate, dict):
            return None
        total = 0
        for name, (low, high) in LIFESTYLE_JUDGE_SUBSCORE_RANGES.items():
            if name not in candidate:
                return None
            try:
                value = int(candidate[name])
            except (TypeError, ValueError):
                return None
            if value < low or value > high:
                return None
            total += value
        totals[label] = total
    return totals


def _case_to_dict(case: ComparisonCase) -> dict[str, Any]:
    data = asdict(case)
    data["rubric"] = [asdict(item) for item in case.rubric]
    return data


def _case_from_dict(data: dict[str, Any]) -> ComparisonCase:
    rubric = tuple(
        RubricCriterion(
            name=str(item["name"]),
            description=str(item["description"]),
            patterns=tuple(str(pattern) for pattern in item["patterns"]),
            weight=int(item.get("weight", 1)),
        )
        for item in data.get("rubric", ())
    )
    return ComparisonCase(
        case_id=str(data["case_id"]),
        skill_name=str(data["skill_name"]),
        prompt=str(data["prompt"]),
        expected_advantage=str(data["expected_advantage"]),
        optimization_if_not_better=str(data["optimization_if_not_better"]),
        scenario=str(data["scenario"]),
        rubric=rubric,
        failure_modes=tuple(str(item) for item in data.get("failure_modes", ())),
    )


def _cases_for_language(language: str) -> list[ComparisonCase]:
    if language == "zh":
        return LIFESTYLE_COMPARISON_CASES
    if language != "en":
        raise SystemExit(f"Unknown prompt language {language!r}. Valid: zh, en")
    localized: list[ComparisonCase] = []
    for case in LIFESTYLE_COMPARISON_CASES:
        localized.append(
            ComparisonCase(
                case_id=f"{case.case_id}_en",
                skill_name=case.skill_name,
                prompt=ENGLISH_LIFESTYLE_PROMPTS[case.case_id],
                expected_advantage=case.expected_advantage,
                optimization_if_not_better=case.optimization_if_not_better,
                scenario=f"{case.scenario}_en",
                rubric=case.rubric,
                failure_modes=case.failure_modes,
            )
        )
    return localized


def _select_cases(case_arg: str, language: str = "zh") -> list[ComparisonCase]:
    cases = _cases_for_language(language)
    if case_arg == "all":
        return cases
    selected = [
        case
        for case in cases
        if case.case_id == case_arg or case.case_id.removesuffix("_en") == case_arg
    ]
    if not selected:
        valid = ", ".join(case.case_id for case in cases)
        raise SystemExit(f"Unknown case {case_arg!r}. Valid: {valid}")
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Run both gateways.")
    parser.add_argument(
        "--judge-jsonl",
        help="Judge an existing lifestyle comparison JSONL without rerunning gateways.",
    )
    parser.add_argument("--write-dry-run", action="store_true", help="Write prompt/catalog reports without live gateway calls.")
    parser.add_argument("--case", default="all", help="Case id or 'all'.")
    parser.add_argument("--prompt-language", choices=["zh", "en"], default="zh")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--opensquilla-url", default="ws://127.0.0.1:18791/ws")
    parser.add_argument("--opensquilla-token", default=read_opensquilla_token())
    parser.add_argument(
        "--opensquilla-agent-id",
        default="main",
        help="Base OpenSquilla agent id for live runs.",
    )
    parser.add_argument(
        "--opensquilla-isolated-agents",
        action="store_true",
        help="Create a distinct OpenSquilla agent id per case to avoid agent-level context pollution.",
    )
    parser.add_argument(
        "--opensquilla-run-id",
        help="Stable run id used in isolated OpenSquilla agent ids.",
    )
    parser.add_argument(
        "--opensquilla-elevated",
        default="bypass",
        choices=["off", "on", "bypass", "full"],
        help="Gateway elevated mode for OpenSquilla tool calls.",
    )
    parser.add_argument("--openclaw-url", default="ws://127.0.0.1:18789/ws")
    parser.add_argument("--openclaw-config", default=os.environ.get("OPENCLAW_CONFIG"))
    parser.add_argument(
        "--openclaw-baseline-jsonl",
        help="Reuse OpenClaw results from an existing report; live run only calls OpenSquilla.",
    )
    parser.add_argument("--openclaw-idle-timeout", type=float, default=90.0)
    parser.add_argument("--judge-llm", action="store_true")
    parser.add_argument("--judge-model", default=os.environ.get("OPENSQUILLA_JUDGE_MODEL"))
    parser.add_argument("--judge-api-key", default=read_judge_api_key())
    parser.add_argument(
        "--judge-base-url",
        default=os.environ.get("OPENSQUILLA_JUDGE_BASE_URL", "https://openrouter.ai/api/v1"),
    )
    parser.add_argument("--judge-timeout", type=float, default=120.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.judge_jsonl:
        asyncio.run(judge_existing(args))
        return
    if args.run_live:
        asyncio.run(run_live(args))
        return
    rows = build_lifestyle_rows(args.prompt_language)
    if args.write_dry_run:
        write_lifestyle_reports(rows)
        return
    print(render_lifestyle_prompts_markdown(rows))


if __name__ == "__main__":
    main()
