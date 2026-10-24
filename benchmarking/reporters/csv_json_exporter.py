"""CSV & JSON Exporter for the MCP Benchmarking Suite.

Outputs:
1. `benchmark_leaderboard.csv`: Model-level leaderboard matching the
   `Model_Benchmark_Results` top summary table in the evaluation workbook
   (including Wilson 95% CI and Wald 95% CI Margin).
2. `benchmark_runs_detailed.csv`: Per-test-case run logs matching the exact columns
   of the `Model_Benchmark_Results` run table (`Run_ID`, `Test_ID`, `Model_Name`,
   `Expected_Tool`, `Actual_Tool_Called`, `Tool_Selection_Accuracy_%`, `Precision@K_%`,
   `Recall@K_%`, `Hierarchy_Inheritance_%`, `Zero_Result_Safety_Abstention_%`,
   `MCP_Timeout_&_Error_Recovery_%`, `Null_Contact_Hallucination_Rate_%`,
   `Context_Token_Efficiency`, `Avg_Latency_ms`, `Total_Tokens`,
   `Production_Composite_Score_%`).
3. `benchmark_report.json`: Complete structured JSON artifact containing model
   summaries, confidence intervals, and individual scorecards.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, ConfigDict

from benchmarking.metrics.aggregator import (
    ModelBenchmarkSummary,
    SingleTestCaseScorecard,
)


class ExportedArtifactsPaths(BaseModel):
    """Paths to the exported CSV and JSON benchmark files."""

    model_config = ConfigDict(extra="forbid")

    leaderboard_csv_path: Path
    detailed_runs_csv_path: Path
    json_report_path: Path


class BenchmarkExporter:
    """Exports aggregated model summaries and detailed test case scorecards to CSV and JSON."""

    LEADERBOARD_CSV_COLUMNS = [
        "Rank",
        "Model_ID",
        "Model_Name",
        "Model_Tier",
        "Sample_Size_N",
        "Overall_Pass_Rate_%",
        "Wald_95_CI_Margin_±%",
        "Wilson_95_CI_Lower_%",
        "Wilson_95_CI_Upper_%",
        "Wilson_95_CI_HalfWidth_±%",
        "Tool_Selection_Accuracy_%",
        "Precision@3_%",
        "Recall@3_%",
        "Hierarchy_Inheritance_%",
        "Zero_Result_Safety_Abstention_%",
        "MCP_Timeout_&_Error_Recovery_%",
        "Null_Contact_Hallucination_Rate_%",
        "Context_Token_Efficiency_%",
        "Production_Composite_Score_%",
        "Avg_TTFT_ms",
        "Avg_Latency_ms",
        "P95_Latency_ms",
        "Total_Tokens",
        "Estimated_Cost_USD",
    ]

    DETAILED_RUNS_CSV_COLUMNS = [
        "Run_ID",
        "Test_ID",
        "Model_Name",
        "Expected_Tool",
        "Actual_Tool_Called",
        "Tool_Selection_Accuracy_%",
        "Precision@K_%",
        "Recall@K_%",
        "Hierarchy_Inheritance_%",
        "Zero_Result_Safety_Abstention_%",
        "MCP_Timeout_&_Error_Recovery_%",
        "Null_Contact_Hallucination_Rate_%",
        "Context_Token_Efficiency",
        "Avg_Latency_ms",
        "Total_Tokens",
        "Production_Composite_Score_%",
        "Passed_Overall",
        "Demographic_or_Language",
        "Section_Category",
        "Failures",
    ]

    def __init__(self, output_dir: str | Path = "benchmarking/results") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_all(
        self,
        summaries: Sequence[ModelBenchmarkSummary],
        scorecards: Sequence[SingleTestCaseScorecard],
        prefix: str = "benchmark",
    ) -> ExportedArtifactsPaths:
        """Write leaderboard CSV, detailed runs CSV, and full JSON report."""
        leaderboard_path = self.output_dir / f"{prefix}_leaderboard.csv"
        detailed_path = self.output_dir / f"{prefix}_runs_detailed.csv"
        json_path = self.output_dir / f"{prefix}_report.json"

        self.export_leaderboard_csv(summaries, leaderboard_path)
        self.export_detailed_runs_csv(scorecards, detailed_path)
        self.export_json_report(summaries, scorecards, json_path)

        return ExportedArtifactsPaths(
            leaderboard_csv_path=leaderboard_path,
            detailed_runs_csv_path=detailed_path,
            json_report_path=json_path,
        )

    def export_leaderboard_csv(
        self,
        summaries: Sequence[ModelBenchmarkSummary],
        file_path: str | Path,
    ) -> Path:
        """Write model-level leaderboard CSV."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.LEADERBOARD_CSV_COLUMNS)
            writer.writeheader()
            for rank, s in enumerate(summaries, start=1):
                ci = s.pass_rate_wilson_95_ci
                writer.writerow(
                    {
                        "Rank": rank,
                        "Model_ID": s.model_id,
                        "Model_Name": s.model_name,
                        "Model_Tier": s.tier,
                        "Sample_Size_N": s.sample_size_n,
                        "Overall_Pass_Rate_%": round(s.overall_pass_rate * 100.0, 2),
                        "Wald_95_CI_Margin_±%": round(ci.wald_margin_of_error * 100.0, 2),
                        "Wilson_95_CI_Lower_%": round(ci.wilson_lower * 100.0, 2),
                        "Wilson_95_CI_Upper_%": round(ci.wilson_upper * 100.0, 2),
                        "Wilson_95_CI_HalfWidth_±%": round(ci.wilson_half_width * 100.0, 2),
                        "Tool_Selection_Accuracy_%": round(s.tool_selection_accuracy_mean * 100.0, 2),
                        "Precision@3_%": round(s.precision_at_k_mean * 100.0, 2),
                        "Recall@3_%": round(s.recall_at_k_mean * 100.0, 2),
                        "Hierarchy_Inheritance_%": round(s.hierarchy_inheritance_mean * 100.0, 2),
                        "Zero_Result_Safety_Abstention_%": round(
                            s.zero_result_safety_abstention_mean * 100.0, 2
                        ),
                        "MCP_Timeout_&_Error_Recovery_%": round(
                            s.mcp_timeout_error_recovery_mean * 100.0, 2
                        ),
                        "Null_Contact_Hallucination_Rate_%": round(
                            s.null_contact_hallucination_rate_mean * 100.0, 2
                        ),
                        "Context_Token_Efficiency_%": round(
                            s.context_token_efficiency_mean * 100.0, 2
                        ),
                        "Production_Composite_Score_%": round(s.composite_score_mean * 100.0, 2),
                        "Avg_TTFT_ms": round(s.ttft_stats.mean_ms, 2),
                        "Avg_Latency_ms": round(s.latency_stats.mean_ms, 2),
                        "P95_Latency_ms": round(s.latency_stats.p95_ms, 2),
                        "Total_Tokens": s.total_tokens_consumed,
                        "Estimated_Cost_USD": round(s.total_estimated_cost_usd, 6),
                    }
                )
        return path

    def export_detailed_runs_csv(
        self,
        scorecards: Sequence[SingleTestCaseScorecard],
        file_path: str | Path,
    ) -> Path:
        """Write per-run detailed scorecard CSV matching the Excel evaluation workbook columns."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.DETAILED_RUNS_CSV_COLUMNS)
            writer.writeheader()
            for sc in scorecards:
                writer.writerow(
                    {
                        "Run_ID": sc.run_id,
                        "Test_ID": sc.test_id,
                        "Model_Name": sc.model_name,
                        "Expected_Tool": sc.expected_tool,
                        "Actual_Tool_Called": sc.actual_tool_called or "",
                        "Tool_Selection_Accuracy_%": round(sc.tool_selection_accuracy, 4),
                        "Precision@K_%": round(sc.precision_at_k, 4),
                        "Recall@K_%": round(sc.recall_at_k, 4),
                        "Hierarchy_Inheritance_%": round(sc.hierarchy_inheritance, 4),
                        "Zero_Result_Safety_Abstention_%": round(sc.zero_result_safety_abstention, 4),
                        "MCP_Timeout_&_Error_Recovery_%": round(sc.mcp_timeout_error_recovery, 4),
                        "Null_Contact_Hallucination_Rate_%": round(
                            sc.null_contact_hallucination_rate, 4
                        ),
                        "Context_Token_Efficiency": round(sc.context_token_efficiency, 4),
                        "Avg_Latency_ms": round(sc.avg_latency_ms, 2),
                        "Total_Tokens": sc.total_tokens,
                        "Production_Composite_Score_%": round(sc.production_composite_score, 4),
                        "Passed_Overall": sc.passed_overall,
                        "Demographic_or_Language": sc.demographic_or_language,
                        "Section_Category": sc.section_category,
                        "Failures": " | ".join(sc.failures),
                    }
                )
        return path

    def export_json_report(
        self,
        summaries: Sequence[ModelBenchmarkSummary],
        scorecards: Sequence[SingleTestCaseScorecard],
        file_path: str | Path,
    ) -> Path:
        """Write full structured JSON benchmark report."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "models_evaluated": len(summaries),
            "total_runs": len(scorecards),
            "leaderboard": [s.model_dump() for s in summaries],
            "runs": [sc.model_dump() for sc in scorecards],
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path
