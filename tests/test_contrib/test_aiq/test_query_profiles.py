"""Offline contract tests for AIQ request-scoped tool surfaces."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import opensquilla.contrib.aiq  # noqa: F401 - registers the AIQ selector
from opensquilla.contrib.aiq.catalog import aiq_tool_names
from opensquilla.contrib.aiq.query_profiles import PROFILES, select_aiq_tool_surface
from opensquilla.engine.tool_surface import (
    filter_tool_definitions,
    registered_tool_surface_agents,
    select_tool_surface,
)
from opensquilla.engine.turn_runner.harness import (
    _TurnRunnerToolSurfaceSelectorAdapter,
)

FAQ_PROFILE_EXPECTATIONS = [
    ("show me top 20 traded bonds by notional value this week", "bond_ranking"),
    (
        "rank the top 10 most active U.S. corporate bonds by traded notional yesterday",
        "bond_ranking",
    ),
    ("break down trading volume for Apr 15 by sector and credit grade", "aggregate"),
    ("top industrials that traded today — rich or poor vs CP+?", "cpplus_screen"),
    ("cheapest bond vs CP+ today in the 5yr maturity", "cpplus_screen"),
    ("why is GD 2.250 06/31 trading cheap vs CP+?", "cpplus_why"),
    ("find me 10 IG energy bonds in the 5-7Y range yielding above 6%", "security_search"),
    ("amazon bonds with a 30 year maturity", "security_search"),
    ("index eligible, 10yr duration, sub $100 price, yields over 4.5%", "constraint_screen"),
    ("biggest spread movers for IG, CP+ close yesterday vs current", "cpplus_movers"),
    ("flag any that widened more than 10bp", "context_followup"),
    ("largest CP+ movement last month", "cpplus_movers"),
    ("show me the most recent trades for Microsoft 4.2% 2035", "prints"),
    ("last 20 trades for Apple 3.35% 2027 with timestamps and sizes", "prints"),
    ("what is a bond ladder", "knowledge"),
    ("CP+ mechanics", "knowledge"),
    ("spread measures", "knowledge"),
    ("how many cusips are in the LQD index", "etf"),
    ("top 20 movers in the Bloomberg HY index", "etf"),
    ("average rating distribution across the full HY index", "etf"),
    ("latest price, yield, spread to treasury, and 1D price change", "security_search"),
    ("where are apple bonds at", "issuer_overview"),
    ("find yield pickup swaps for portfolio X", "portfolio_swaps"),
    ("analyze each of these rich vs cheap swaps and rank by risk", "portfolio_swaps"),
    ("does gainwell have bonds", "security_search"),
    ("show me where NVDA bonds are trading", "issuer_overview"),
    ("graph of curve of amazon bonds", "curve_chart"),
    ("what sector risk do I have", "portfolio_analysis"),
    ("sector weightings", "portfolio_analysis"),
    ("graph of cashflows over time", "portfolio_analysis"),
    ("rating distribution, duration", "portfolio_analysis"),
    ("run a liquidity scan on portfolio X", "portfolio_liquidity"),
    (
        "most actively traded bonds today and reasons behind their liquidity",
        "bond_ranking",
    ),
    (
        "build a $100mm IG portfolio mirroring LQD risk, outperform by 25bps, 35 holdings",
        "portfolio_build",
    ),
    ("build me a simple bond ladder", "portfolio_ladder"),
    ("how big was TRACE volume in IG yesterday", "aggregate"),
    ("which sectors saw the most net buying this week", "aggregate"),
    ("high yield names with unusual volume", "unusual_volume"),
    ("037833AL4", "security_search"),
    ("G-spread on a daily basis", "history_chart"),
    ("graph g spread for these bonds", "history_chart"),
    ("remove all communications and increase consumer staples", "portfolio_rebalance"),
    (
        "should I execute all 3 sector rebalancing trades or phase them in",
        "portfolio_rebalance",
    ),
    ("load insight details, explain why surfaced, verify claims against latest data", "insight"),
    ("how do munis look relative to treasurys", "knowledge"),
    ("recent interest rates", "rates"),
    ("yesterday's top 10 high yield movers", "movers"),
    ("top performing technology bonds this week", "movers"),
    ("how have new issue IG bonds performed the last 5 trading sessions", "new_issue"),
    ("how has the recent spacex deal done", "new_issue"),
]


FAQ_21_EXPECTATIONS = [
    (
        "caq-t01",
        "rank the top 10 most active U.S. corporate bonds by traded notional yesterday",
        "bond_ranking",
        ("securities_search",),
    ),
    (
        "caq-t02",
        "top industrials that traded today — are they rich or poor vs CP+?",
        "cpplus_screen",
        ("securities_search",),
    ),
    (
        "caq-t03",
        "find me 10 IG energy bonds in the 5-7Y range yielding above 6%",
        "security_search",
        ("securities_search",),
    ),
    (
        "caq-t04",
        (
            "biggest spread movers for IG, CP+ close yesterday vs current — "
            "flag any that widened more than 10bp"
        ),
        "cpplus_movers",
        ("mktx_cpp_movers",),
    ),
    (
        "caq-t05",
        "show me the most recent trades for Microsoft 4.2% 2035",
        "prints",
        ("securities_search",),
    ),
    ("caq-t06", "what is a bond ladder", "knowledge", ()),
    ("caq-t07", "how many cusips are in the LQD index", "etf", ("etf_reference",)),
    (
        "caq-t08",
        "give me the latest price, yield, and spread to treasury for Apple 3.35% 2027",
        "security_search",
        ("securities_search",),
    ),
    (
        "caq-t09",
        "find yield pickup swaps for my portfolio",
        "portfolio_swaps",
        (
            "portfolio_list",
            "portfolio_list_holdings",
            "securities_search",
            "bond_lookalikes",
            "bond_calculate",
        ),
    ),
    ("caq-t10", "show me where NVDA bonds are trading", "issuer_overview", ("securities_search",)),
    (
        "caq-t11",
        "what sector risk do I have in my portfolio",
        "portfolio_analysis",
        ("portfolio_list", "portfolio_list_holdings", "portfolio_analytics", "render_chart"),
    ),
    (
        "caq-t12",
        "which are the most actively traded bonds today, and the reasons behind their liquidity?",
        "bond_ranking",
        ("securities_search",),
    ),
    ("caq-t13", "build me a simple bond ladder", "portfolio_ladder", ("securities_search",)),
    ("caq-t14", "how big was TRACE volume in IG yesterday", "aggregate", ("trace_notional",)),
    ("caq-t15", "037833AL4", "security_search", ("securities_search",)),
    (
        "caq-t16",
        "plot the G-spread on a daily basis for Apple 3.35% 2027",
        "history_chart",
        ("securities_search", "prints_group_by_period", "render_chart"),
    ),
    (
        "caq-t17",
        "remove all communications and increase consumer staples in my portfolio",
        "portfolio_rebalance",
        (
            "portfolio_list",
            "portfolio_list_holdings",
            "portfolio_analytics",
            "generate_portfolio_proposal",
            "portfolio_remove_holding",
            "portfolio_add_holding",
            "portfolio_swap",
        ),
    ),
    (
        "caq-t18",
        (
            "load this insight's details, explain why it was surfaced, and verify the claims "
            "against the latest data"
        ),
        "insight",
        ("get_insight", "securities_search", "trace_notional", "get_rates_snapshot", "news_search"),
    ),
    ("caq-t19", "how do munis look relative to treasurys right now", "knowledge", ()),
    ("caq-t20", "show me yesterday's top 10 high yield movers", "movers", ("movers_search",)),
    (
        "caq-t21",
        "how have new issue IG bonds performed over the last 5 trading sessions",
        "new_issue",
        ("securities_search",),
    ),
]


@pytest.mark.parametrize(("query", "expected"), FAQ_PROFILE_EXPECTATIONS)
def test_all_captured_faq_queries_match_native_profile_contract(
    query: str,
    expected: str,
) -> None:
    selection = select_aiq_tool_surface(query)
    assert selection is not None
    assert selection.profile == expected


@pytest.mark.parametrize(("case_id", "query", "profile", "expected_tools"), FAQ_21_EXPECTATIONS)
def test_exact_faq_21_tool_contract(
    case_id: str,
    query: str,
    profile: str,
    expected_tools: tuple[str, ...],
) -> None:
    selection = select_aiq_tool_surface(query)
    assert selection is not None, case_id
    assert selection.profile == profile, case_id
    assert tuple(name for name in selection.tool_names if name != "skill_view") == expected_tools
    assert selection.max_iterations is not None and selection.max_iterations > 0
    assert selection.repeat_call_threshold == 2


def test_profiles_have_unique_small_surfaces_and_at_most_one_skill() -> None:
    for selection in PROFILES.values():
        assert len(selection.tool_names) == len(set(selection.tool_names))
        assert len(selection.tool_names) <= 7
        assert selection.skill_name is None or isinstance(selection.skill_name, str)
        assert ("skill_view" in selection.tool_names) is bool(selection.skill_name)
        assert selection.preload_skill is bool(selection.skill_name)
        assert selection.max_iterations is not None and selection.max_iterations > 0
        assert selection.repeat_call_threshold == 2


def test_every_profile_tool_exists_in_the_aiq_bridge_catalog() -> None:
    bridged = set(aiq_tool_names())
    selected = {
        tool_name
        for selection in PROFILES.values()
        for tool_name in selection.tool_names
        if tool_name != "skill_view"
    }
    assert selected <= bridged


def test_unknown_query_fails_open_to_full_surface() -> None:
    assert select_aiq_tool_surface("compare this bespoke scenario") is None


def test_registered_selector_is_active_for_aiq_only() -> None:
    assert "aiq" in registered_tool_surface_agents()
    selection = select_tool_surface("aiq", "recent interest rates")
    assert selection is not None
    assert selection.tool_names == ("get_rates_snapshot",)
    assert select_tool_surface("main", "recent interest rates") is None


def test_surface_filter_can_remove_but_never_add_authorized_tools() -> None:
    definitions = [
        SimpleNamespace(name="securities_search"),
        SimpleNamespace(name="trace_notional"),
    ]
    selection = PROFILES["history_chart"]
    filtered = filter_tool_definitions(definitions, selection)
    assert [definition.name for definition in filtered] == ["securities_search"]


def test_activity_profile_blocks_the_three_call_failure_path() -> None:
    selection = select_aiq_tool_surface("show me top 20 traded bonds by notional value this week")
    assert selection is not None
    assert selection.tool_names == ("securities_search", "skill_view")
    assert "prints_search" not in selection.tool_names
    assert "trace_notional" not in selection.tool_names


def test_faq_profiles_expose_the_parameters_needed_for_exact_requests() -> None:
    monthly_cpp = select_aiq_tool_surface("largest CP+ movement last month")
    issuer_curve = select_aiq_tool_surface("graph of curve of amazon bonds")
    portfolio = select_aiq_tool_surface(
        "build a $100mm IG portfolio mirroring LQD risk, outperform by 25bps, 35 holdings"
    )

    assert monthly_cpp is not None
    assert "lookback_days=30" in monthly_cpp.guidance
    assert issuer_curve is not None
    assert "source_mode='issuer_yield_curve'" in issuer_curve.guidance
    assert portfolio is not None
    assert "target_yield_pickup_bps" in portfolio.guidance


def test_runtime_adapter_filters_tools_and_catalog_to_one_skill() -> None:
    definitions = [
        SimpleNamespace(name="prints_search"),
        SimpleNamespace(name="trace_notional"),
        SimpleNamespace(name="securities_search"),
        SimpleNamespace(name="skill_view"),
    ]
    catalog = SimpleNamespace(
        generation=1,
        skills=(
            SimpleNamespace(
                name="aiq-bond-activity-leaderboards",
                content="# Bond activity leaderboards\nCall securities_search once.",
            ),
            SimpleNamespace(name="aiq-rankings-and-leaderboards"),
        ),
    )

    selected_defs, selected_catalog, metadata, guidance = (
        _TurnRunnerToolSurfaceSelectorAdapter().select(
            agent_id="aiq",
            semantic_message="show me top 20 traded bonds by notional value this week",
            tool_defs=definitions,
            skill_catalog=catalog,
        )
    )

    assert [definition.name for definition in selected_defs] == ["securities_search"]
    assert selected_catalog.skills == ()
    assert metadata["query_tool_count_before"] == 4
    assert metadata["query_tool_count_after"] == 1
    assert metadata["query_skill_found"] is True
    assert metadata["query_skill_preloaded"] is True
    assert metadata["query_max_iterations"] == 1
    assert metadata["query_repeat_call_threshold"] == 2
    assert "Bond activity leaderboards" in metadata["_query_preloaded_skill_context"]
    assert "never repeat a successful call" in guidance


def test_runtime_adapter_removes_tools_and_skills_for_concept_question() -> None:
    definitions = [SimpleNamespace(name="securities_search"), SimpleNamespace(name="skill_view")]
    catalog = SimpleNamespace(
        generation=1,
        skills=(SimpleNamespace(name="aiq-entity-resolution"),),
    )

    selected_defs, selected_catalog, metadata, _guidance = (
        _TurnRunnerToolSurfaceSelectorAdapter().select(
            agent_id="aiq",
            semantic_message="what is a bond ladder",
            tool_defs=definitions,
            skill_catalog=catalog,
        )
    )

    assert selected_defs == []
    assert selected_catalog.skills == ()
    assert metadata["query_tool_profile"] == "knowledge"
