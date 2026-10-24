"""Model Composite Score Aggregator for the MCP Benchmarking Suite.

Combines deterministic evaluator outputs (`ToolSelectionEvaluator`,
`GraphTraversalEvaluator`, `SafetyAbstentionEvaluator`, `RegexASTCheckerEvaluator`),
operational fault recovery, and token/latency telemetry into:
- Per-test-case scorecards (`SingleTestCaseScorecard`) matching the columns of
  `Model_Benchmark_Results` in the evaluation Excel workbook.
- Model-level aggregated summaries (`ModelBenchmarkSummary`) with Wilson 95%
  confidence intervals, category breakdowns, and DuckDB / DataFrame export support.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from benchmarking.evaluators.base import EvaluationContext, EvaluatorResult
from benchmarking.metrics.statistics import (
    ConfidenceIntervalBound,
    LatencyDistributionStats,
    compute_latency_percentiles,
    compute_wilson_confidence_interval,
)


class CompositeWeightsConfig(BaseModel):
    """Weights used to compute the `Production_Composite_Score_%` for each test case and model."""

    model_config = ConfigDict(extra="forbid")

    tool_selection_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    precision_recall_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    hierarchy_inheritance_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    safety_abstention_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    error_recovery_weight: float = Field(default=0.10, ge=0.0, le=1.0)
    contact_grounding_weight: float = Field(default=0.10, ge=0.0, le=1.0)
    token_efficiency_weight: float = Field(default=0.05, ge=0.0, le=1.0)


class SingleTestCaseScorecard(BaseModel):
    """Complete deterministic scorecard for a single (model, test_case) execution."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    test_id: str
    model_id: str
    model_name: str
    tier: str
    section_category: str
    demographic_or_language: str
    expected_tool: str
    actual_tool_called: str | None
    passed_overall: bool

    tool_selection_accuracy: float = Field(..., ge=0.0, le=1.0)
    precision_at_k: float = Field(..., ge=0.0, le=1.0)
    recall_at_k: float = Field(..., ge=0.0, le=1.0)
    hierarchy_inheritance: float = Field(..., ge=0.0, le=1.0)
    zero_result_safety_abstention: float = Field(..., ge=0.0, le=1.0)
    mcp_timeout_error_recovery: float = Field(..., ge=0.0, le=1.0)
    null_contact_hallucination_rate: float = Field(..., ge=0.0, le=1.0)
    context_token_efficiency: float = Field(..., ge=0.0, le=1.0)

    ttft_ms: float = Field(default=0.0, ge=0.0)
    avg_latency_ms: float = Field(default=0.0, ge=0.0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    production_composite_score: float = Field(..., ge=0.0, le=1.0)
    failures: list[str] = Field(default_factory=list)


class ModelBenchmarkSummary(BaseModel):
    """Aggregated model-level benchmark results with Wilson 95% confidence intervals."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    model_name: str
    tier: str
    sample_size_n: int
    overall_pass_rate: float
    pass_rate_wilson_95_ci: ConfidenceIntervalBound
    composite_score_mean: float
    composite_score_wilson_95_ci: ConfidenceIntervalBound

    tool_selection_accuracy_mean: float
    precision_at_k_mean: float
    recall_at_k_mean: float
    hierarchy_inheritance_mean: float
    zero_result_safety_abstention_mean: float
    mcp_timeout_error_recovery_mean: float
    null_contact_hallucination_rate_mean: float
    context_token_efficiency_mean: float

    latency_stats: LatencyDistributionStats
    ttft_stats: LatencyDistributionStats
    total_tokens_consumed: int
    total_estimated_cost_usd: float
    section_pass_rates: dict[str, ConfidenceIntervalBound] = Field(default_factory=dict)


class ScoreAggregator:
    """Computes per-test scorecards and model-level composite scores with Wilson 95% CIs."""

    def __init__(
        self,
        weights: CompositeWeightsConfig | None = None,
        token_budget_target: int = 2000,
    ) -> None:
        self.weights = weights or CompositeWeightsConfig()
        self.token_budget_target = max(100, token_budget_target)

    def build_test_scorecard(
        self,
        run_id: str,
        context: EvaluationContext,
        tool_eval: EvaluatorResult,
        graph_eval: EvaluatorResult,
        safety_eval: EvaluatorResult,
        regex_eval: EvaluatorResult,
        error_recovery_score: float = 1.0,
    ) -> SingleTestCaseScorecard:
        """Combine individual evaluator results for a single test case into a `SingleTestCaseScorecard`."""
        inv = context.model_invocation
        model_id = inv.model_id if inv else "unknown"
        model_name = inv.model_name if inv else "Unknown Model"
        tier = inv.tier if inv else "frontier"
        called_tool = inv.intercepted_tool_calls[0].tool_name if (inv and inv.intercepted_tool_calls) else None

        total_tokens = inv.usage.total_tokens if inv else 0
        ttft_ms = inv.ttft_ms if inv else 0.0
        mcp_latency = sum(r.latency_ms for r in context.mcp_tool_results)
        total_latency_ms = (inv.roundtrip_latency_ms if inv else 0.0) + mcp_latency
        cost_usd = inv.usage.estimated_cost_usd if inv else 0.0

        tool_acc = tool_eval.score
        p_at_k = graph_eval.sub_scores.get("precision_at_3", graph_eval.score)
        r_at_k = graph_eval.sub_scores.get("recall_at_3", graph_eval.score)
        hierarchy_score = graph_eval.sub_scores.get("hierarchy_traversal_score", graph_eval.score)

        is_zero_result_case = len(context.golden_target_iris_or_ids) == 0
        safety_score = safety_eval.score if is_zero_result_case else 1.0

        hallucination_rate = regex_eval.sub_scores.get("hallucination_rate", 0.0)
        contact_grounding = 1.0 - hallucination_rate

        if total_tokens <= 0:
            token_efficiency = 1.0
        elif total_tokens <= self.token_budget_target:
            token_efficiency = 1.0
        else:
            token_efficiency = max(
                0.0,
                round(self.token_budget_target / float(total_tokens), 4),
            )

        pr_mean = 0.5 * (p_at_k + r_at_k)
        w = self.weights
        composite = (
            w.tool_selection_weight * tool_acc
            + w.precision_recall_weight * pr_mean
            + w.hierarchy_inheritance_weight * hierarchy_score
            + w.safety_abstention_weight * safety_score
            + w.error_recovery_weight * error_recovery_score
            + w.contact_grounding_weight * contact_grounding
            + w.token_efficiency_weight * token_efficiency
        )
        composite = round(min(1.0, max(0.0, composite)), 4)

        all_failures: list[str] = []
        all_failures.extend(tool_eval.failures)
        if not is_zero_result_case:
            all_failures.extend(graph_eval.failures)
        else:
            all_failures.extend(safety_eval.failures)
        all_failures.extend(regex_eval.failures)

        if is_zero_result_case:
            passed_overall = tool_eval.passed and safety_eval.passed and regex_eval.passed
        else:
            passed_overall = tool_eval.passed and graph_eval.passed and regex_eval.passed

        return SingleTestCaseScorecard(
            run_id=run_id,
            test_id=context.test_id,
            model_id=model_id,
            model_name=model_name,
            tier=tier,
            section_category=context.section_category,
            demographic_or_language=context.demographic_or_language,
            expected_tool=context.expected_tool,
            actual_tool_called=called_tool,
            passed_overall=passed_overall,
            tool_selection_accuracy=round(tool_acc, 4),
            precision_at_k=round(p_at_k, 4),
            recall_at_k=round(r_at_k, 4),
            hierarchy_inheritance=round(hierarchy_score, 4),
            zero_result_safety_abstention=round(safety_score, 4),
            mcp_timeout_error_recovery=round(error_recovery_score, 4),
            null_contact_hallucination_rate=round(hallucination_rate, 4),
            context_token_efficiency=round(token_efficiency, 4),
            ttft_ms=round(ttft_ms, 2),
            avg_latency_ms=round(total_latency_ms, 2),
            total_tokens=total_tokens,
            estimated_cost_usd=round(cost_usd, 6),
            production_composite_score=composite,
            failures=all_failures,
        )

    @staticmethod
    def aggregate_model_results(
        scorecards: list[SingleTestCaseScorecard],
        confidence_level: float = 0.95,
    ) -> list[ModelBenchmarkSummary]:
        """Group scorecards by `model_id` and compute composite metrics + Wilson 95% confidence intervals."""
        if not scorecards:
            return []

        by_model: dict[str, list[SingleTestCaseScorecard]] = {}
        for sc in scorecards:
            by_model.setdefault(sc.model_id, []).append(sc)

        summaries: list[ModelBenchmarkSummary] = []
        for model_id, cards in by_model.items():
            n = len(cards)
            first = cards[0]
            pass_count = sum(1 for c in cards if c.passed_overall)
            composite_sum = sum(c.production_composite_score for c in cards)

            pass_ci = compute_wilson_confidence_interval(
                successes=pass_count,
                n=n,
                confidence_level=confidence_level,
            )
            comp_ci = compute_wilson_confidence_interval(
                successes=composite_sum,
                n=n,
                confidence_level=confidence_level,
            )

            section_groups: dict[str, list[SingleTestCaseScorecard]] = {}
            for c in cards:
                section_groups.setdefault(c.section_category, []).append(c)

            section_cis: dict[str, ConfidenceIntervalBound] = {}
            for sec_name, sec_cards in sorted(section_groups.items()):
                sec_passes = sum(1 for c in sec_cards if c.passed_overall)
                section_cis[sec_name] = compute_wilson_confidence_interval(
                    successes=sec_passes,
                    n=len(sec_cards),
                    confidence_level=confidence_level,
                )

            summaries.append(
                ModelBenchmarkSummary(
                    model_id=model_id,
                    model_name=first.model_name,
                    tier=first.tier,
                    sample_size_n=n,
                    overall_pass_rate=round(pass_count / float(n), 4),
                    pass_rate_wilson_95_ci=pass_ci,
                    composite_score_mean=round(composite_sum / float(n), 4),
                    composite_score_wilson_95_ci=comp_ci,
                    tool_selection_accuracy_mean=round(sum(c.tool_selection_accuracy for c in cards) / float(n), 4),
                    precision_at_k_mean=round(sum(c.precision_at_k for c in cards) / float(n), 4),
                    recall_at_k_mean=round(sum(c.recall_at_k for c in cards) / float(n), 4),
                    hierarchy_inheritance_mean=round(sum(c.hierarchy_inheritance for c in cards) / float(n), 4),
                    zero_result_safety_abstention_mean=round(
                        sum(c.zero_result_safety_abstention for c in cards) / float(n), 4
                    ),
                    mcp_timeout_error_recovery_mean=round(
                        sum(c.mcp_timeout_error_recovery for c in cards) / float(n), 4
                    ),
                    null_contact_hallucination_rate_mean=round(
                        sum(c.null_contact_hallucination_rate for c in cards) / float(n), 4
                    ),
                    context_token_efficiency_mean=round(
                        sum(c.context_token_efficiency for c in cards) / float(n), 4
                    ),
                    latency_stats=compute_latency_percentiles([c.avg_latency_ms for c in cards]),
                    ttft_stats=compute_latency_percentiles([c.ttft_ms for c in cards]),
                    total_tokens_consumed=sum(c.total_tokens for c in cards),
                    total_estimated_cost_usd=round(sum(c.estimated_cost_usd for c in cards), 6),
                    section_pass_rates=section_cis,
                )
            )

        return sorted(summaries, key=lambda s: s.composite_score_mean, reverse=True)

    @staticmethod
    def query_with_duckdb(
        scorecards: list[SingleTestCaseScorecard],
        sql_query: str = (
            "SELECT model_name, COUNT(*) AS n, "
            "ROUND(AVG(production_composite_score) * 100, 2) AS composite_pct, "
            "ROUND(AVG(null_contact_hallucination_rate) * 100, 2) AS hallucination_pct, "
            "ROUND(AVG(avg_latency_ms), 1) AS avg_latency_ms "
            "FROM scorecards GROUP BY model_name ORDER BY composite_pct DESC"
        ),
    ) -> list[dict[str, Any]]:
        """Run analytical SQL aggregations over scorecards using DuckDB in-memory engine."""
        if not scorecards:
            return []
        df = pd.DataFrame([c.model_dump(exclude={"failures"}) for c in scorecards])
        con = duckdb.connect(database=":memory:")
        try:
            con.register("scorecards", df)
            res_df = con.execute(sql_query).df()
            return res_df.to_dict(orient="records")
        finally:
            con.close()
