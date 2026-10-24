"""Statistical confidence intervals and composite benchmark score aggregation."""

from benchmarking.metrics.aggregator import (
    CompositeWeightsConfig,
    ModelBenchmarkSummary,
    ScoreAggregator,
    SingleTestCaseScorecard,
)
from benchmarking.metrics.statistics import (
    ConfidenceIntervalBound,
    LatencyDistributionStats,
    compute_latency_percentiles,
    compute_wald_confidence_interval,
    compute_wilson_confidence_interval,
)

__all__ = [
    "CompositeWeightsConfig",
    "ConfidenceIntervalBound",
    "LatencyDistributionStats",
    "ModelBenchmarkSummary",
    "ScoreAggregator",
    "SingleTestCaseScorecard",
    "compute_latency_percentiles",
    "compute_wald_confidence_interval",
    "compute_wilson_confidence_interval",
]
