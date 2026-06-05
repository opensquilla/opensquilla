"""Semantic retrieval guardrails for high-value meta-skills."""

from __future__ import annotations

_COMPETITIVE_INTEL_CUES = (
    "competitive",
    "competitor",
    "rival",
    "baseline",
    "account signal",
    "sales brief",
    "strategy brief",
    "竞品",
    "竞争情报",
    "对手",
    "对标",
    "基线",
    "账户信号",
    "竞对",
)

_NEGATIVE_CUES_BY_SKILL = {
    "meta-skill-creator": (
        "normal standalone skill",
        "standalone skill",
        "not a meta-skill",
        "not a meta skill",
        "普通 skill",
        "普通技能",
        "不是 meta",
    ),
    "meta-document-to-decision": (
        "summarize this contract excerpt generally",
        "summarize generally",
        "not deciding",
        "not deciding whether",
        "not decide whether",
        "i am not deciding",
        "generic summarization",
        "通用总结",
        "只是总结",
        "不决定",
        "不判断签不签",
    ),
    "meta-web-research-to-report": (
        "just answer briefly",
        "briefly, no report",
        "no report",
        "no citations",
        "without citations",
        "isolated fact",
        "只是回答",
        "简单回答",
        "不用报告",
        "不要报告",
        "不用来源",
    ),
    "meta-paper-write": (
        "summarize this paper",
        "paper summary",
        "list the main claims",
        "main claims",
        "literature-search-only",
        "paper summaries",
        "总结这篇论文",
        "论文总结",
        "主要观点",
    ),
    "meta-daily-operator-brief": (
        "single reminder",
        "one reminder",
        "set one reminder",
        "remind me",
        "move one meeting",
        "isolated scheduling",
        "single tool",
        "提醒我",
        "设置一个提醒",
        "一个提醒",
        "移动一个会议",
    ),
    "meta-short-drama": (
        "not a video",
        "not video",
        "not a video or mp4",
        "not a video or final mp4",
        "script idea",
        "isolated script writing",
        "storyboard-only",
        "video ideas without generation",
        "不要视频",
        "不用成片",
        "只写脚本",
        "脚本创意",
        "只要分镜",
    ),
    "meta-kid-project-planner": (
        "adult craft",
        "not my child",
        "not a child",
        "not for a child",
        "adult project",
        "成人手工",
        "成人项目",
        "不是孩子",
        "不是儿童",
        "不是孩子作业",
    ),
    "meta-job-search-pipeline": (
        "career advice",
        "better resume in general",
        "generic resume",
        "without a target role",
        "without a jd",
        "no target role",
        "no jd",
        "what does career application mean",
        "职业建议",
        "泛泛简历建议",
        "通用简历建议",
        "没有岗位",
        "没有 jd",
    ),
}

_POSITIVE_CUES_BY_SKILL = {
    "meta-skill-creator": (
        "create a meta-skill",
        "new meta-skill",
        "synthesize meta-skill",
        "compose meta-skill",
        "meta skill",
        "orchestrates existing skills",
        "orchestrate existing skills",
        "compose existing skills",
        "组合现有 skill",
        "新增 meta 技能",
        "meta 技能",
        "元技能",
    ),
    "meta-document-to-decision": (
        "document decision",
        "decide whether",
        "whether to sign",
        "sign, reject, or negotiate",
        "vendor renewal",
        "renewal risk",
        "evidence table",
        "questions for the vendor",
        "contract risk",
        "签不签",
        "要不要签",
        "要不要接受",
        "合同风险",
        "报价单分析",
        "供应商续费",
        "续费材料",
        "决定",
        "判断",
    ),
    "meta-web-research-to-report": (
        "source-backed",
        "cited research report",
        "cited report",
        "decision memo with sources",
        "with sources",
        "technical briefing",
        "market briefing",
        "research report",
        "write up the sourced findings",
        "source-backed writeup",
        "带来源",
        "来源、关键发现",
        "调研报告",
        "创始团队",
        "核心员工",
        "估值",
        "技术路线",
        "股东",
        "融资",
        "决策备忘",
        "报告",
    ),
    "meta-paper-write": (
        "draft a paper",
        "write a research paper",
        "academic manuscript",
        "research manuscript",
        "latex manuscript",
        "long-form research paper",
        "compile",
        "manuscript",
        "写篇论文",
        "写一篇论文",
        "撰写论文",
        "论文草稿",
        "latex",
    ),
    "meta-daily-operator-brief": (
        "daily operating brief",
        "daily brief",
        "morning brief",
        "today operating plan",
        "daily priority",
        "day schedule",
        "calendar",
        "task context",
        "today priorities",
        "今日简报",
        "早上简报",
        "今天优先级",
        "今天先做什么",
        "今天先帮我排一下优先级",
        "今天前三优先级",
        "今天时间块",
    ),
    "meta-short-drama": (
        "generate a short drama",
        "generate short drama",
        "make a short drama",
        "short drama mp4",
        "final mp4",
        "shot list to final mp4",
        "video clips",
        "生成短剧",
        "做一个ai短剧",
        "帮我做一个短剧",
        "分镜成片",
        "短视频分镜成片",
        "成片",
        "最终mp4",
    ),
    "meta-kid-project-planner": (
        "child's school project",
        "child science",
        "science fair",
        "help my kid build",
        "kid science",
        "child diy project",
        "school project",
        "孩子做项目",
        "孩子做一个安全手工项目",
        "科学课作业",
        "课外动手项目",
        "儿童项目",
        "孩子作业",
    ),
    "meta-job-search-pipeline": (
        "tailor my resume",
        "tailor my resume to this job",
        "job application pack",
        "application pack for this role",
        "interview prep for",
        "application tracker",
        "pasted jd",
        "target role",
        "target company",
        "根据jd改简历",
        "根据岗位改简历",
        "针对这个岗位",
        "求职投递包",
        "求职申请追踪",
        "岗位改简历",
    ),
}


def _has_any(text: str, cues: tuple[str, ...]) -> bool:
    return any(cue in text for cue in cues)


def semantic_meta_skill_allowed(skill_name: str, query: str) -> bool:
    """Return whether a semantic-only match may surface this meta-skill.

    Deterministic triggers remain the high-precision path. This guard handles
    retrieval/embedding similarity and direct model calls, where neighboring
    requests can look close to a bundled workflow without actually asking for
    the end-to-end deliverable.
    """

    text = (query or "").lower()
    if skill_name == "meta-competitive-intel":
        return _has_any(text, _COMPETITIVE_INTEL_CUES)

    negative_cues = _NEGATIVE_CUES_BY_SKILL.get(skill_name)
    if negative_cues and _has_any(text, negative_cues):
        return False

    positive_cues = _POSITIVE_CUES_BY_SKILL.get(skill_name)
    if positive_cues is not None:
        return _has_any(text, positive_cues)

    return True


__all__ = ["semantic_meta_skill_allowed"]
