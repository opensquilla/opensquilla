"""High-precision request profiles for the OpenSquilla AIQ agent.

This is the standalone port of AIQ's deterministic query-profile boundary.
It intentionally recognizes only stable, high-frequency request families.  A
miss returns ``None`` and therefore keeps the full AIQ tool/skill surface.

Profiles narrow model-visible context and bound ordinary tool-loop iterations;
they do not bypass OpenSquilla's tool policy or AIQ's backend validation. Each
matched profile exposes the minimum useful tools, preloads at most one workflow
skill, and supplies a short stop/routing contract derived from the FAQ
regression set.
"""

from __future__ import annotations

import re

from opensquilla.engine.tool_surface import ToolSurfaceSelection

_CUSIP_RE = re.compile(r"^[0-9A-Z*@#]{9}$", re.I)


def _selection(
    profile: str,
    *tool_names: str,
    skill_name: str | None = None,
    max_iterations: int = 1,
    guidance: str = "",
) -> ToolSurfaceSelection:
    names = list(dict.fromkeys(tool_names))
    if skill_name and "skill_view" not in names:
        names.append("skill_view")
    return ToolSurfaceSelection(
        profile=profile,
        tool_names=tuple(names),
        skill_name=skill_name,
        preload_skill=skill_name is not None,
        max_iterations=max_iterations,
        repeat_call_threshold=2,
        guidance=guidance,
    )


PROFILES: dict[str, ToolSurfaceSelection] = {
    "knowledge": _selection(
        "knowledge",
        guidance=(
            "Answer directly without a data tool. Do not invent current levels. CP+ is a "
            "MarketAxess modelled cash-price fair value; G-spread is versus Treasurys. "
            "State the corporate-TRACE scope boundary for muni/cross-asset questions."
        ),
    ),
    "context_followup": _selection(
        "context_followup",
        guidance=(
            "Apply the requested filter or explanation to prior-turn rows. If those rows are "
            "not present, ask for them; do not launch a replacement market scan."
        ),
    ),
    "rates": _selection(
        "rates",
        "get_rates_snapshot",
        guidance="Call get_rates_snapshot once and report its returned source and as-of.",
    ),
    "bond_ranking": _selection(
        "bond_ranking",
        "securities_search",
        skill_name="aiq-bond-activity-leaderboards",
        guidance=(
            "Make one compact securities_search activity call, preserve bond grain, requested "
            "metric/N/window and server order, then stop; never repeat a successful call or "
            "expand a successful compact result. Do not try prints_search or trace_notional "
            "first. For liquidity reasons, use only literal returned score/trades/notional/days/"
            "last_trade observables; do not invent causes."
        ),
    ),
    "aggregate": _selection(
        "aggregate",
        "trace_notional",
        skill_name="aiq-aggregation-correctness",
        guidance=(
            "Call trace_notional once with an exact resolved date. Use sector_credit for sector "
            "x grade, credit_grade for total IG/HY volume, and net_flow ordered by net_buying "
            "for customer flow. Preserve TRACE cap/lower-bound caveats."
        ),
    ),
    "cpplus_screen": _selection(
        "cpplus_screen",
        "securities_search",
        skill_name="aiq-benchmark-methodology",
        guidance=(
            "Use one securities_search. Use cpp_cheap/cpp_rich for cheapest/richest; use full "
            "detail immediately when activity and CP+ fields are both requested. CP+ price "
            "differences are points of par, never basis points."
        ),
    ),
    "cpplus_why": _selection(
        "cpplus_why",
        "securities_search",
        skill_name="aiq-benchmark-methodology",
        guidance=(
            "Resolve and enrich the bond with one full securities_search including recent "
            "prints and CP+ history. Do not guess a CUSIP or manufacture causal drivers."
        ),
    ),
    "cpplus_movers": _selection(
        "cpplus_movers",
        "mktx_cpp_movers",
        skill_name="aiq-rankings-and-leaderboards",
        guidance=(
            "Call mktx_cpp_movers once. Its delta is a CP+ cash-price move in points of par, "
            "not a Treasury-adjusted spread move in basis points. Preserve its dates. If the "
            "request asks for widening in bps, state that the tool cannot establish or flag it; "
            "never relabel the price move."
        ),
    ),
    "security_search": _selection(
        "security_search",
        "securities_search",
        skill_name="aiq-entity-resolution",
        guidance=(
            "Compose all issuer, identifier, maturity, grade, price, yield, duration, and "
            "eligibility constraints in one securities_search. Never relax them silently."
        ),
    ),
    "constraint_screen": _selection(
        "constraint_screen",
        "securities_search",
        skill_name="aiq-entity-resolution",
        guidance=(
            "Use one full securities_search with every numeric constraint. There is no generic "
            "canonical index-eligibility flag; do not substitute 144A status."
        ),
    ),
    "issuer_overview": _selection(
        "issuer_overview",
        "securities_search",
        skill_name="aiq-entity-resolution",
        guidance=(
            "Use one full issuer securities_search, show a maturity-ordered representative page, "
            "and disclose total/truncation. Make no all-issuer claim from one page."
        ),
    ),
    "prints": _selection(
        "prints",
        "securities_search",
        skill_name="aiq-entity-resolution",
        guidance=(
            "Resolve the named bond and request recent prints in one securities_search with "
            "detail=compact, include_recent_prints=true, and the requested recent_prints_limit. "
            "Read only the verified CUSIP's related_data; do not call prints_search separately. "
            "Preserve timestamps and capped-size minimum disclosures."
        ),
    ),
    "etf": _selection(
        "etf",
        "etf_reference",
        skill_name="aiq-rankings-and-leaderboards",
        guidance=(
            "Only LQD and HYG held-constituent datasets are supported. Never relabel a "
            "market-wide HY scan as Bloomberg-index members or movers."
        ),
    ),
    "curve_chart": _selection(
        "curve_chart",
        "render_chart",
        skill_name="aiq-charting-and-visualization",
        guidance=(
            "Call render_chart once in issuer_yield_curve mode; it retrieves issuer bonds "
            "internally. Do not call securities_search separately."
        ),
    ),
    "history_chart": _selection(
        "history_chart",
        "securities_search",
        "prints_group_by_period",
        "render_chart",
        skill_name="aiq-charting-and-visualization",
        max_iterations=3,
        guidance=(
            "Resolve real CUSIPs, retrieve the daily G-spread series with "
            "prints_group_by_period(include_g_spread=true), then render that series."
        ),
    ),
    "unusual_volume": _selection(
        "unusual_volume",
        "volume_surge_search",
        skill_name="aiq-rankings-and-leaderboards",
        guidance=(
            "Call volume_surge_search once and preserve its anomaly metric/baseline. Do not "
            "substitute an ordinary most-active ranking."
        ),
    ),
    "movers": _selection(
        "movers",
        "movers_search",
        skill_name="aiq-rankings-and-leaderboards",
        guidance=(
            "Call movers_search once with the requested grade/sector/session/direction. Preserve "
            "price-point versus yield/spread-basis-point units exactly."
        ),
    ),
    "new_issue": _selection(
        "new_issue",
        "securities_search",
        skill_name="aiq-new-issuance-queries",
        guidance=(
            "Use one compact securities_search with issue dates, requested grade/issuer, and "
            "include_period_history=day for a trading-session performance request. Compute change "
            "only from returned VWAP endpoints. Empty/short history is a coverage gap, not proof "
            "of no trading or performance; never assume issue price was par."
        ),
    ),
    "insight": _selection(
        "insight",
        "get_insight",
        "securities_search",
        "trace_notional",
        "get_rates_snapshot",
        "news_search",
        max_iterations=4,
        guidance=(
            "An insight id or prior-turn insight is required. If absent, ask for it and do not "
            "invent details. If present, call get_insight first, then verify only its actual "
            "market claims with the smallest relevant fresh data call. Separate stored claims "
            "from verified facts and never claim verification when the supporting tool is absent."
        ),
    ),
    "portfolio_build": _selection(
        "portfolio_build",
        "generate_portfolio_proposal",
        guidance=(
            "Call generate_portfolio_proposal once with all mandate constraints. Report actual "
            "constraint checks; never invent why an optimizer target was missed."
        ),
    ),
    "portfolio_ladder": _selection(
        "portfolio_ladder",
        "securities_search",
        skill_name="aiq-bond-ladder-construction",
        guidance=(
            "Build a concrete ladder in one securities_search using maturity_ladder_years and "
            "sensible stated defaults. Returned activity is liquidity evidence, not portfolio "
            "principal; equal proposed rung principal must be computed from the stated budget."
        ),
    ),
    "portfolio_swaps": _selection(
        "portfolio_swaps",
        "portfolio_list",
        "portfolio_list_holdings",
        "securities_search",
        "bond_lookalikes",
        "bond_calculate",
        max_iterations=5,
        guidance=(
            "Resolve the portfolio once, inspect actual holdings, and ground "
            "sell-to-buy candidates and duration/risk. If a referenced swap set "
            "is absent, ask for it."
        ),
    ),
    "portfolio_analysis": _selection(
        "portfolio_analysis",
        "portfolio_list",
        "portfolio_list_holdings",
        "portfolio_analytics",
        "render_chart",
        skill_name="aiq-portfolio-concentration",
        max_iterations=3,
        guidance=(
            "Resolve the portfolio and compute sector/rating/duration/cash-flow answers only from "
            "its holdings and analytics. Render a chart only when requested."
        ),
    ),
    "portfolio_liquidity": _selection(
        "portfolio_liquidity",
        "portfolio_list",
        "portfolio_list_holdings",
        "portfolio_liquidation_analysis",
        "securities_search",
        max_iterations=4,
        guidance=(
            "Resolve the real portfolio and holdings before liquidity analysis. Explain scores "
            "only with returned activity/tradability evidence."
        ),
    ),
    "portfolio_rebalance": _selection(
        "portfolio_rebalance",
        "portfolio_list",
        "portfolio_list_holdings",
        "portfolio_analytics",
        "generate_portfolio_proposal",
        "portfolio_remove_holding",
        "portfolio_add_holding",
        "portfolio_swap",
        max_iterations=4,
        guidance=(
            "Verify holdings before proposing changes. Never claim execution; writes require the "
            "normal confirmation and authorization path."
        ),
    ),
}


def select_aiq_tool_surface(query: str) -> ToolSurfaceSelection | None:
    """Return the narrow AIQ profile for a known request, else full surface."""

    text = " ".join((query or "").strip().lower().split())
    if not text:
        return None
    if _CUSIP_RE.fullmatch(text.upper()):
        return PROFILES["security_search"]

    # Portfolio families precede generic market phrases such as yield/sector.
    if "ladder" in text and any(term in text for term in ("build", "create", "construct")):
        return PROFILES["portfolio_ladder"]
    if ("build" in text or "create" in text) and "portfolio" in text:
        return PROFILES["portfolio_build"]
    if any(
        term in text for term in ("yield pickup swap", "these rich vs cheap swaps", "rank by risk")
    ):
        return PROFILES["portfolio_swaps"]
    if "liquidity scan" in text and "portfolio" in text:
        return PROFILES["portfolio_liquidity"]
    if any(
        term in text
        for term in ("remove all communications", "sector rebalancing trade", "rebalance")
    ):
        return PROFILES["portfolio_rebalance"]
    if (
        "portfolio" in text
        or text in {"sector weightings", "rating distribution, duration"}
        or "sector risk do i have" in text
        or "cashflows over time" in text
    ):
        return PROFILES["portfolio_analysis"]

    if "insight" in text:
        return PROFILES["insight"]
    if any(
        term in text for term in ("recent interest rates", "treasury rates", "yield curve today")
    ):
        return PROFILES["rates"]
    if any(term in text for term in ("lqd", "hyg", "bloomberg hy index", "full hy index")):
        return PROFILES["etf"]
    if "unusual volume" in text or "volume surge" in text or "volume spike" in text:
        return PROFILES["unusual_volume"]
    if any(term in text for term in ("new issue", "newly issued", "recent deal", "spacex deal")):
        return PROFILES["new_issue"]
    if "graph" in text or "chart" in text or "plot" in text or "daily basis" in text:
        if "curve of" in text and "g spread" not in text and "g-spread" not in text:
            return PROFILES["curve_chart"]
        if "g spread" in text or "g-spread" in text:
            return PROFILES["history_chart"]
    if "most recent trades" in text or "last 20 trades" in text:
        return PROFILES["prints"]
    if text.startswith("flag any") or text.startswith("analyze these"):
        return PROFILES["context_followup"]
    if "why" in text and "cp+" in text:
        return PROFILES["cpplus_why"]
    if "cp+" in text and any(
        term in text for term in ("cheapest", "rich or poor", "rich or cheap")
    ):
        return PROFILES["cpplus_screen"]
    if "cp+" in text and any(
        term in text for term in ("mover", "movement", "close yesterday", "widened")
    ):
        return PROFILES["cpplus_movers"]
    if any(term in text for term in ("break down trading volume", "trace volume", "net buying")):
        return PROFILES["aggregate"]
    if "mover" in text or "top performing" in text or "widened more than" in text:
        return PROFILES["movers"]
    if any(
        term in text
        for term in (
            "most active",
            "most actively traded",
            "top traded bonds",
            "traded bonds by notional",
        )
    ):
        return PROFILES["bond_ranking"]
    if "index eligible" in text:
        return PROFILES["constraint_screen"]
    if "where are apple bonds" in text or "where nvda bonds" in text:
        return PROFILES["issuer_overview"]
    if any(
        term in text
        for term in (
            "find me",
            "bonds with",
            "where are apple bonds",
            "where nvda bonds",
            "does gainwell",
            "latest price",
            "index eligible",
        )
    ):
        return PROFILES["security_search"]
    if (
        text.startswith("what is ")
        or text in {"cp+ mechanics", "spread measures"}
        or "how do munis look" in text
    ):
        return PROFILES["knowledge"]
    return None


__all__ = ["PROFILES", "select_aiq_tool_surface"]
