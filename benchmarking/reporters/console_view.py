"""Rich Terminal Dashboard for the Federated Data Pool MCP Benchmarking Suite.

Renders:
- Execution configuration header panel (transport, suite size, concurrency, dry-run status)
- Model Leaderboard Summary table showing Composite Score %, Wilson 95% CI, Tool Accuracy %,
  Precision@3 %, Hierarchy Inheritance %, Zero-Result Safety %, Hallucination Rate %,
  Avg/P95 Latency (ms), Total Tokens, and Estimated Cost ($)
- Stratified Section & Category breakdown table
- Sample Failure Diagnostics table
"""

from __future__ import annotations

from typing import Sequence

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from benchmarking.core.mcp_client import ToolSchemaIntrospectionReport
from benchmarking.metrics.aggregator import (
    ModelBenchmarkSummary,
    SingleTestCaseScorecard,
)


class BenchmarkConsoleDashboard:
    """Renders formatted Rich tables and panels for MCP benchmark runs."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(width=185, force_terminal=True)

    def render_run_header(
        self,
        suite_path: str,
        total_cases: int,
        model_names: Sequence[str],
        transport: str,
        concurrency: int,
        dry_run: bool,
    ) -> None:
        """Render the top banner with benchmark parameters."""
        mode_badge = "[bold yellow]DRY-RUN (Deterministic Mock MCP + Simulated Telemetry)[/bold yellow]" if dry_run else "[bold green]LIVE MCP EVALUATION[/bold green]"
        body = (
            f"[bold cyan]Suite:[/bold cyan] {suite_path} ([bold]{total_cases}[/bold] test cases)\n"
            f"[bold cyan]Models ({len(model_names)}):[/bold cyan] {', '.join(model_names)}\n"
            f"[bold cyan]MCP Transport:[/bold cyan] {transport.upper()}  |  "
            f"[bold cyan]Max Concurrency:[/bold cyan] {concurrency}  |  "
            f"[bold cyan]Execution Mode:[/bold cyan] {mode_badge}"
        )
        self.console.print(
            Panel(
                body,
                title="[bold white]DSSG Berlin Datathon 2026 — Federated Data Pool MCP Benchmark Harness[/bold white]",
                border_style="bright_blue",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    def render_schema_introspection(self, report: ToolSchemaIntrospectionReport) -> None:
        """Render MCP tool schema compliance check against `tools_schema.json`."""
        status_str = (
            "[bold green]COMPLIANT (All 5 Core Tools Verified)[/bold green]"
            if report.is_core_compliant
            else "[bold red]SCHEMA DRIFT DETECTED[/bold red]"
        )
        lines = [
            f"Compliance Status: {status_str}",
            f"Matched Core Tools ({len(report.matched_core_tools)}/{len(report.expected_core_tools)}): {', '.join(report.matched_core_tools) or 'None'}",
        ]
        if report.missing_core_tools:
            lines.append(f"[red]Missing Core Tools:[/red] {', '.join(report.missing_core_tools)}")
        if report.parameter_mismatches:
            lines.append(f"[yellow]Parameter Mismatches:[/yellow] {len(report.parameter_mismatches)} tool(s)")

        self.console.print(
            Panel(
                "\n".join(lines),
                title="[bold cyan]MCP Server Tool Introspection (`list_tools()` vs `tools_schema.json`)[/bold cyan]",
                border_style="cyan",
                box=box.SIMPLE_HEAVY,
            )
        )

    def render_leaderboard(self, summaries: Sequence[ModelBenchmarkSummary]) -> None:
        """Render the primary model comparison leaderboard table."""
        table = Table(
            title="[bold white]Model Evaluation Leaderboard (Ranked by Production Composite Score)[/bold white]",
            box=box.HEAVY_HEAD,
            show_lines=True,
            header_style="bold bright_cyan",
        )

        table.add_column("Rank", justify="center", style="bold", no_wrap=True)
        table.add_column("Model Name", style="bold white", no_wrap=True)
        table.add_column("Tier", style="dim", no_wrap=True)
        table.add_column("N", justify="right", no_wrap=True)
        table.add_column("Composite %", justify="right", style="bold green", no_wrap=True)
        table.add_column("Pass Rate % (Wilson 95% CI)", justify="right", no_wrap=True)
        table.add_column("Tool Acc %", justify="right", no_wrap=True)
        table.add_column("Prec@3 %", justify="right", no_wrap=True)
        table.add_column("Hierarchy %", justify="right", no_wrap=True)
        table.add_column("Safety %", justify="right", no_wrap=True)
        table.add_column("Halluc %", justify="right", no_wrap=True)
        table.add_column("Avg / P95 Latency", justify="right", no_wrap=True)
        table.add_column("Tokens", justify="right", no_wrap=True)
        table.add_column("Cost ($)", justify="right", no_wrap=True)

        for idx, s in enumerate(summaries, start=1):
            ci = s.pass_rate_wilson_95_ci
            pass_pct = s.overall_pass_rate * 100.0
            ci_low = ci.wilson_lower * 100.0
            ci_high = ci.wilson_upper * 100.0
            hw = ci.wilson_half_width * 100.0

            halluc_pct = s.null_contact_hallucination_rate_mean * 100.0
            halluc_style = "bold green" if halluc_pct <= 5.0 else ("bold yellow" if halluc_pct <= 15.0 else "bold red")

            table.add_row(
                f"#{idx}",
                s.model_name,
                s.tier.upper(),
                str(s.sample_size_n),
                f"{s.composite_score_mean * 100.0:.1f}%",
                f"{pass_pct:.1f}% (±{hw:.1f}% [{ci_low:.1f}–{ci_high:.1f}])",
                f"{s.tool_selection_accuracy_mean * 100.0:.1f}%",
                f"{s.precision_at_k_mean * 100.0:.1f}%",
                f"{s.hierarchy_inheritance_mean * 100.0:.1f}%",
                f"{s.zero_result_safety_abstention_mean * 100.0:.1f}%",
                Text(f"{halluc_pct:.1f}%", style=halluc_style),
                f"{s.latency_stats.mean_ms:.0f} / {s.latency_stats.p95_ms:.0f} ms",
                f"{s.total_tokens_consumed:,}",
                f"${s.total_estimated_cost_usd:.4f}",
            )

        self.console.print(table)

    def render_section_breakdown(self, summaries: Sequence[ModelBenchmarkSummary]) -> None:
        """Render pass rates broken down by evaluation section across models."""
        if not summaries:
            return
        all_sections = sorted(
            {sec for s in summaries for sec in s.section_pass_rates.keys()}
        )
        if not all_sections:
            return

        table = Table(
            title="[bold white]Stratified Pass Rate (%) by Evaluation Section[/bold white]",
            box=box.SIMPLE_HEAD,
            header_style="bold magenta",
        )
        table.add_column("Evaluation Section", style="bold")
        for s in summaries:
            table.add_column(s.model_name, justify="right")

        for sec in all_sections:
            row_vals = [sec]
            for s in summaries:
                bound = s.section_pass_rates.get(sec)
                if bound is None or bound.n == 0:
                    row_vals.append("N/A")
                else:
                    row_vals.append(f"{bound.proportion * 100.0:.1f}% (n={bound.n})")
            table.add_row(*row_vals)

        self.console.print(table)

    def render_failure_highlights(
        self,
        scorecards: Sequence[SingleTestCaseScorecard],
        max_rows: int = 8,
    ) -> None:
        """Render a concise diagnostic table of failed test cases and caught traps."""
        failed = [sc for sc in scorecards if not sc.passed_overall and sc.failures]
        if not failed:
            self.console.print("[bold green]All evaluated test cases passed with 0 deterministic failures![/bold green]")
            return

        table = Table(
            title=f"[bold yellow]Diagnostic Failure Highlights (Showing top {min(len(failed), max_rows)} of {len(failed)} failed runs)[/bold yellow]",
            box=box.MINIMAL_DOUBLE_HEAD,
            header_style="bold yellow",
        )
        table.add_column("Run ID", style="dim")
        table.add_column("Test ID", style="bold")
        table.add_column("Model", style="cyan")
        table.add_column("Expected Tool")
        table.add_column("Called Tool")
        table.add_column("Deterministic Failure Reason", style="red")

        for sc in failed[:max_rows]:
            table.add_row(
                sc.run_id,
                sc.test_id,
                sc.model_name,
                sc.expected_tool,
                sc.actual_tool_called or "NONE",
                "; ".join(sc.failures[:2]),
            )

        self.console.print(table)
