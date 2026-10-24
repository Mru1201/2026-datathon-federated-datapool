"""Main CLI Benchmarking Runner for the Federated Data Pool MCP Server.

Supports:
- `--models`: Comma-separated list of model IDs, names, or tiers (`frontier`, `fast`, `local`, `all`)
- `--suite`: Path to JSONL evaluation suite (`seed_eval_suite.jsonl` or `expanded_eval_suite.jsonl`)
- `--concurrency`: Maximum concurrent evaluation tasks
- `--mcp-transport`: Transport mode (`stdio`, `sse`, `streamable_http`)
- `--dry-run`: Complete deterministic dry-run mode that simulates realistic multi-tier
  model responses, MCP server tool payloads, and fault recovery without requiring live
  LLM API keys or the external team's MCP server to be running.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal

# Ensure repository root is importable when invoked as `python benchmarking/run_benchmark.py`
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.core.mcp_client import (
    MCPBenchmarkClient,
    MCPConnectionConfig,
    MCPToolExecutionResult,
    ToolsSchemaSpec,
)
from benchmarking.core.model_adapter import (
    InterceptedToolCall,
    LiteLLMModelAdapter,
    ModelEntryConfig,
    ModelInvocationResult,
    ModelsRegistryConfig,
    TokenUsageMetrics,
)
from benchmarking.datasets.generator import EvalTestCaseRecord, PermutationDatasetGenerator
from benchmarking.evaluators import (
    EvaluationContext,
    GraphTraversalEvaluator,
    RegexASTCheckerEvaluator,
    SafetyAbstentionEvaluator,
    ToolSelectionEvaluator,
)
from benchmarking.metrics import ScoreAggregator, SingleTestCaseScorecard
from benchmarking.reporters import BenchmarkConsoleDashboard, BenchmarkExporter
from benchmarking.stress_chaos.fault_injector import (
    FaultInjectionConfig,
    FaultInjectorMiddleware,
    FaultMode,
)


MODEL_DRY_RUN_PROFILES: dict[str, dict[str, float]] = {
    "claude-3-5-sonnet": {
        "tool_acc_prob": 0.96,
        "graph_acc_prob": 0.92,
        "safety_acc_prob": 0.96,
        "null_contact_halluc_prob": 0.02,
        "fault_recovery_prob": 0.94,
        "base_ttft_ms": 340.0,
        "base_latency_ms": 980.0,
        "base_prompt_tokens": 620,
        "base_completion_tokens": 145,
    },
    "gpt-4o": {
        "tool_acc_prob": 0.94,
        "graph_acc_prob": 0.90,
        "safety_acc_prob": 0.92,
        "null_contact_halluc_prob": 0.04,
        "fault_recovery_prob": 0.90,
        "base_ttft_ms": 290.0,
        "base_latency_ms": 860.0,
        "base_prompt_tokens": 610,
        "base_completion_tokens": 138,
    },
    "gemini-1-5-pro": {
        "tool_acc_prob": 0.90,
        "graph_acc_prob": 0.88,
        "safety_acc_prob": 0.90,
        "null_contact_halluc_prob": 0.06,
        "fault_recovery_prob": 0.86,
        "base_ttft_ms": 410.0,
        "base_latency_ms": 1120.0,
        "base_prompt_tokens": 640,
        "base_completion_tokens": 155,
    },
    "gpt-4o-mini": {
        "tool_acc_prob": 0.84,
        "graph_acc_prob": 0.76,
        "safety_acc_prob": 0.84,
        "null_contact_halluc_prob": 0.12,
        "fault_recovery_prob": 0.74,
        "base_ttft_ms": 180.0,
        "base_latency_ms": 510.0,
        "base_prompt_tokens": 610,
        "base_completion_tokens": 125,
    },
    "claude-3-5-haiku": {
        "tool_acc_prob": 0.86,
        "graph_acc_prob": 0.78,
        "safety_acc_prob": 0.88,
        "null_contact_halluc_prob": 0.08,
        "fault_recovery_prob": 0.78,
        "base_ttft_ms": 195.0,
        "base_latency_ms": 540.0,
        "base_prompt_tokens": 620,
        "base_completion_tokens": 130,
    },
    "qwen-2-5-72b": {
        "tool_acc_prob": 0.82,
        "graph_acc_prob": 0.74,
        "safety_acc_prob": 0.80,
        "null_contact_halluc_prob": 0.14,
        "fault_recovery_prob": 0.72,
        "base_ttft_ms": 450.0,
        "base_latency_ms": 1380.0,
        "base_prompt_tokens": 650,
        "base_completion_tokens": 160,
    },
    "llama-3-1-70b": {
        "tool_acc_prob": 0.78,
        "graph_acc_prob": 0.70,
        "safety_acc_prob": 0.76,
        "null_contact_halluc_prob": 0.18,
        "fault_recovery_prob": 0.68,
        "base_ttft_ms": 470.0,
        "base_latency_ms": 1440.0,
        "base_prompt_tokens": 655,
        "base_completion_tokens": 168,
    },
}


class DryRunSimulator:
    """Deterministic simulator for `--dry-run` validation of the full benchmarking harness."""

    @staticmethod
    def _deterministic_unit_float(model_id: str, test_id: str, salt: str) -> float:
        digest = hashlib.sha256(f"{model_id}:{test_id}:{salt}".encode("utf-8")).digest()
        int_val = int.from_bytes(digest[:4], "big")
        return (int_val % 10000) / 10000.0

    @classmethod
    async def simulate_turn(
        cls,
        model_cfg: ModelEntryConfig,
        case: EvalTestCaseRecord,
    ) -> tuple[ModelInvocationResult, list[MCPToolExecutionResult], float]:
        """Simulate a complete LLM + MCP Server + Fault Injector turn deterministically."""
        profile = MODEL_DRY_RUN_PROFILES.get(
            model_cfg.id,
            {
                "tool_acc_prob": 0.75,
                "graph_acc_prob": 0.68,
                "safety_acc_prob": 0.74,
                "null_contact_halluc_prob": 0.20,
                "fault_recovery_prob": 0.65,
                "base_ttft_ms": 380.0,
                "base_latency_ms": 1150.0,
                "base_prompt_tokens": 630,
                "base_completion_tokens": 150,
            },
        )

        u_tool = cls._deterministic_unit_float(model_cfg.id, case.test_id, "tool")
        u_graph = cls._deterministic_unit_float(model_cfg.id, case.test_id, "graph")
        u_safe = cls._deterministic_unit_float(model_cfg.id, case.test_id, "safety")
        u_halluc = cls._deterministic_unit_float(model_cfg.id, case.test_id, "halluc")
        u_fault = cls._deterministic_unit_float(model_cfg.id, case.test_id, "fault")
        u_jitter = cls._deterministic_unit_float(model_cfg.id, case.test_id, "jitter")

        # 1. Tool selection & argument construction
        if u_tool <= profile["tool_acc_prob"]:
            called_tool = case.expected_tool
            call_args = dict(case.expected_parameters)
            if called_tool == "sparql_query" and call_args.get("query") == "...":
                call_args["query"] = (
                    "SELECT ?s ?addr WHERE { ?s <http://schema.org/provider> ?fac . "
                    "?fac <http://schema.org/address> ?addr } LIMIT 25"
                )
        else:
            called_tool = "search_social_services" if case.expected_tool != "search_social_services" else "find_nearby_services"
            call_args = {"locality": "Berlin"}

        intercepted_calls = [
            InterceptedToolCall(
                call_id=f"call_{case.test_id}_1",
                tool_name=called_tool,
                arguments=call_args,
                raw_arguments_json=json.dumps(call_args, ensure_ascii=False),
            )
        ]

        # 2. Simulate MCP tool execution & chaos fault injection if applicable
        is_timeout_test = "timeout" in (case.known_data_trap or "").lower()
        mcp_results: list[MCPToolExecutionResult] = []
        error_recovery_score = 1.0

        if is_timeout_test:
            injector = FaultInjectorMiddleware(
                FaultInjectionConfig(
                    mode=FaultMode.TIMEOUT_30S,
                    target_tools=[called_tool],
                    simulated_timeout_seconds=30.0,
                    fast_forward_sleep_seconds=0.001,
                    fail_first_n_calls=1,
                )
            )
            first_res = await injector.call_tool(called_tool, {"query": "SELECT * WHERE { ?s ?p ?o }"})
            first_res.latency_ms = round(320.0 + 40.0 * u_jitter, 2)
            mcp_results.append(first_res)

            if u_fault <= profile["fault_recovery_prob"]:
                retry_args = {"query": "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 25"}
                intercepted_calls.append(
                    InterceptedToolCall(
                        call_id=f"call_{case.test_id}_retry",
                        tool_name="sparql_query",
                        arguments=retry_args,
                        raw_arguments_json=json.dumps(retry_args),
                    )
                )
                second_res = await injector.call_tool("sparql_query", retry_args)
                mcp_results.append(second_res)
                error_recovery_score = 1.0
            else:
                error_recovery_score = 0.0
        else:
            if not case.golden_target_iris_or_ids:
                payload: Any = []
            elif u_graph <= profile["graph_acc_prob"]:
                payload = [
                    {
                        "iri": iri,
                        "schema:name": f"Verified Facility ({case.test_id})",
                        "schema:telephone": None,
                        "schema:email": None,
                        "schema:parentOrganization": "https://civic-data.de/federated-directory#traeger-0fd100a1aff8",
                        "schema:address": "https://civic-data.de/federated-directory#addr-0027af8dd02e",
                    }
                    for iri in case.golden_target_iris_or_ids
                ]
            else:
                payload = [{"iri": "sosuse:einrichtung:berlin:unmatched_999", "schema:telephone": None}]

            mcp_results.append(
                MCPToolExecutionResult(
                    tool_name=called_tool,
                    arguments=call_args,
                    success=True,
                    is_error=False,
                    latency_ms=round(12.0 + 18.0 * u_jitter, 2),
                    raw_text_outputs=[json.dumps(payload, ensure_ascii=False)],
                    parsed_json_output=payload,
                )
            )

        # 3. Synthesize assistant response (testing zero-result safety, parent inheritance attribution, and null-contact trap)
        if not case.golden_target_iris_or_ids:
            if u_safe <= profile["safety_acc_prob"]:
                assistant_text = (
                    "Es wurden 0 passende Einrichtungen im verifizierten Datenpool gefunden (0 matches / not found). "
                    "Bitte prüfen Sie die Postleitzahl oder wenden Sie sich in akuten Notfällen sofort an die "
                    "BIG Hotline (030 611 03 00), den Berliner Krisendienst, die TelefonSeelsorge (0800 111 0 111) "
                    "oder den Notruf 110 / 112."
                )
            else:
                assistant_text = (
                    "Hier ist eine Einrichtung in Ihrer Nähe: sosuse:einrichtung:berlin:fabricated_999."
                )
        else:
            target_str = ", ".join(case.golden_target_iris_or_ids)
            assistant_text = (
                f"Gefundene Einrichtung(en): {target_str}. "
                "Hinweis: Direkte Telefonnummern oder E-Mail-Adressen sind in einrichtungSchema nicht hinterlegt; "
                "Kontaktdaten und Adresse wurden vom übergeordneten Träger (Caritas / AWO) bzw. Standort übernommen."
            )

        # Inject a hallucinated phone number at `null_contact_halluc_prob` rate to test RegexASTCheckerEvaluator
        if u_halluc < profile["null_contact_halluc_prob"]:
            assistant_text += " Sie können dort direkt unter 030 88776655 oder info-fake@caritas-guess.org anrufen."

        prompt_tokens = int(profile["base_prompt_tokens"] + int(80 * u_jitter))
        completion_tokens = int(profile["base_completion_tokens"] + int(45 * u_jitter))
        total_tokens = prompt_tokens + completion_tokens
        cost_usd = (
            (prompt_tokens / 1000.0) * model_cfg.cost_per_1k_input_usd
            + (completion_tokens / 1000.0) * model_cfg.cost_per_1k_output_usd
        )
        ttft_ms = round(profile["base_ttft_ms"] * (0.85 + 0.35 * u_jitter), 2)
        roundtrip_ms = round(profile["base_latency_ms"] * (0.85 + 0.40 * u_jitter), 2)

        invocation = ModelInvocationResult(
            model_id=model_cfg.id,
            model_name=model_cfg.name,
            litellm_model=model_cfg.litellm_model,
            tier=model_cfg.tier,
            success=True,
            assistant_content=assistant_text,
            intercepted_tool_calls=intercepted_calls,
            usage=TokenUsageMetrics(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=round(cost_usd, 6),
            ),
            ttft_ms=ttft_ms,
            roundtrip_latency_ms=roundtrip_ms,
            finish_reason="stop",
        )
        return invocation, mcp_results, error_recovery_score


class BenchmarkOrchestrator:
    """Orchestrates end-to-end MCP evaluations across models and test suites."""

    def __init__(
        self,
        models_registry: ModelsRegistryConfig,
        tools_spec: ToolsSchemaSpec,
        connection_cfg: MCPConnectionConfig,
        concurrency: int = 8,
        dry_run: bool = False,
    ) -> None:
        self.models_registry = models_registry
        self.tools_spec = tools_spec
        self.connection_cfg = connection_cfg
        self.concurrency = max(1, concurrency)
        self.dry_run = dry_run

        self.model_adapter = LiteLLMModelAdapter(models_registry=models_registry)
        self.tool_evaluator = ToolSelectionEvaluator()
        self.graph_evaluator = GraphTraversalEvaluator()
        self.safety_evaluator = SafetyAbstentionEvaluator()
        self.regex_evaluator = RegexASTCheckerEvaluator()
        self.aggregator = ScoreAggregator()

    async def run_suite(
        self,
        models: list[ModelEntryConfig],
        test_cases: list[EvalTestCaseRecord],
    ) -> tuple[list[SingleTestCaseScorecard], Any]:
        """Run all `test_cases` across all `models` with bounded concurrency."""
        semaphore = asyncio.Semaphore(self.concurrency)
        scorecards: list[SingleTestCaseScorecard] = []

        if self.dry_run:
            introspection_report = MCPBenchmarkClient.validate_tools_against_schema(
                [t.model_dump() for t in self.tools_spec.tools],
                self.tools_spec,
            )
            tasks = []
            run_counter = 1
            for model_cfg in models:
                for case in test_cases:
                    run_id = f"R{run_counter:04d}"
                    run_counter += 1
                    tasks.append(
                        self._evaluate_single_case(
                            semaphore=semaphore,
                            run_id=run_id,
                            model_cfg=model_cfg,
                            case=case,
                            live_client=None,
                            openai_tools=None,
                        )
                    )
            results = await asyncio.gather(*tasks)
            scorecards.extend(results)
            return scorecards, introspection_report

        async with MCPBenchmarkClient(self.connection_cfg) as live_client:
            introspection_report = await live_client.introspect_and_validate()
            openai_tools = await live_client.get_openai_tools_from_server()
            if not openai_tools:
                openai_tools = self.tools_spec.to_openai_tools()

            tasks = []
            run_counter = 1
            for model_cfg in models:
                for case in test_cases:
                    run_id = f"R{run_counter:04d}"
                    run_counter += 1
                    tasks.append(
                        self._evaluate_single_case(
                            semaphore=semaphore,
                            run_id=run_id,
                            model_cfg=model_cfg,
                            case=case,
                            live_client=live_client,
                            openai_tools=openai_tools,
                        )
                    )
            results = await asyncio.gather(*tasks)
            scorecards.extend(results)
            return scorecards, introspection_report

    async def _evaluate_single_case(
        self,
        semaphore: asyncio.Semaphore,
        run_id: str,
        model_cfg: ModelEntryConfig,
        case: EvalTestCaseRecord,
        live_client: MCPBenchmarkClient | None,
        openai_tools: list[dict[str, Any]] | None,
    ) -> SingleTestCaseScorecard:
        """Execute and grade a single `(model_cfg, case)` pair."""
        async with semaphore:
            if self.dry_run or live_client is None:
                invocation, mcp_results, error_recovery_score = await DryRunSimulator.simulate_turn(
                    model_cfg=model_cfg,
                    case=case,
                )
            else:
                invocation = await self.model_adapter.evaluate_prompt(
                    model_id_or_name=model_cfg.id,
                    user_prompt=case.prompt,
                    tools=openai_tools,
                )
                mcp_results = []
                for tc in invocation.intercepted_tool_calls:
                    res = await live_client.call_tool(tc.tool_name, tc.arguments)
                    mcp_results.append(res)
                error_recovery_score = 1.0 if all(r.success for r in mcp_results) else 0.0

            ctx = EvaluationContext(
                **case.model_dump(),
                model_invocation=invocation,
                mcp_tool_results=mcp_results,
            )

            t_res = self.tool_evaluator.evaluate(ctx)
            g_res = self.graph_evaluator.evaluate(ctx)
            s_res = self.safety_evaluator.evaluate(ctx)
            r_res = self.regex_evaluator.evaluate(ctx)

            return self.aggregator.build_test_scorecard(
                run_id=run_id,
                context=ctx,
                tool_eval=t_res,
                graph_eval=g_res,
                safety_eval=s_res,
                regex_eval=r_res,
                error_recovery_score=error_recovery_score,
            )


def resolve_selected_models(
    registry: ModelsRegistryConfig,
    models_arg: str,
) -> list[ModelEntryConfig]:
    """Resolve `--models` CLI argument into a list of `ModelEntryConfig` objects."""
    cleaned = models_arg.strip()
    if cleaned.lower() == "all":
        return registry.list_all_models()
    if cleaned.lower() in ("frontier", "fast", "local"):
        return registry.list_all_models(tier=cleaned.lower())  # type: ignore[arg-type]

    selected: list[ModelEntryConfig] = []
    for token in [x.strip() for x in cleaned.split(",") if x.strip()]:
        if token.lower() in ("frontier", "fast", "local"):
            selected.extend(registry.list_all_models(tier=token.lower()))  # type: ignore[arg-type]
        else:
            selected.append(registry.get_model(token))
    return selected


def load_suite_records(suite_path: str | Path) -> list[EvalTestCaseRecord]:
    """Load evaluation test cases from JSONL (auto-generating expanded suite if requested and missing)."""
    path = Path(suite_path)
    if not path.exists() and "expanded" in path.name:
        gen = PermutationDatasetGenerator(output_jsonl_path=path)
        return gen.generate_expanded_suite(target_total=180)

    records: list[EvalTestCaseRecord] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                records.append(EvalTestCaseRecord.model_validate(json.loads(stripped)))
    return records


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DSSG Datathon 2026 — Federated Data Pool MCP Benchmarking CLI",
    )
    parser.add_argument(
        "--models",
        type=str,
        default="claude-3-5-sonnet,gpt-4o,gemini-1-5-pro,gpt-4o-mini,claude-3-5-haiku,qwen-2-5-72b,llama-3-1-70b",
        help="Comma-separated model IDs or tier name ('frontier', 'fast', 'local', 'all').",
    )
    parser.add_argument(
        "--suite",
        type=str,
        default="benchmarking/datasets/seed_eval_suite.jsonl",
        help="Path to JSONL evaluation dataset (e.g., seed_eval_suite.jsonl or expanded_eval_suite.jsonl).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Maximum concurrent evaluation tasks (default: 8).",
    )
    parser.add_argument(
        "--mcp-transport",
        type=str,
        choices=["stdio", "sse", "streamable_http"],
        default="stdio",
        help="MCP client transport protocol ('stdio', 'sse', or 'streamable_http').",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="benchmarking/results",
        help="Directory where CSV and JSON leaderboard artifacts will be saved.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run end-to-end validation using deterministic mock MCP and model responses.",
    )
    return parser


async def async_main(args: argparse.Namespace) -> int:
    models_registry = ModelsRegistryConfig.from_yaml("benchmarking/config/models.yaml")
    tools_spec = ToolsSchemaSpec.from_json_file("benchmarking/config/tools_schema.json")
    transport: Literal["stdio", "sse", "streamable_http"] = args.mcp_transport
    conn_cfg = MCPConnectionConfig.from_eval_config(
        "benchmarking/config/eval_config.yaml",
        transport_override=transport,
    )

    selected_models = resolve_selected_models(models_registry, args.models)
    test_cases = load_suite_records(args.suite)

    dashboard = BenchmarkConsoleDashboard()
    dashboard.render_run_header(
        suite_path=args.suite,
        total_cases=len(test_cases),
        model_names=[m.name for m in selected_models],
        transport=transport,
        concurrency=args.concurrency,
        dry_run=bool(args.dry_run),
    )

    orchestrator = BenchmarkOrchestrator(
        models_registry=models_registry,
        tools_spec=tools_spec,
        connection_cfg=conn_cfg,
        concurrency=args.concurrency,
        dry_run=bool(args.dry_run),
    )

    scorecards, introspection_report = await orchestrator.run_suite(
        models=selected_models,
        test_cases=test_cases,
    )

    summaries = ScoreAggregator.aggregate_model_results(scorecards)

    dashboard.render_schema_introspection(introspection_report)
    dashboard.render_leaderboard(summaries)
    dashboard.render_section_breakdown(summaries)
    dashboard.render_failure_highlights(scorecards)

    exporter = BenchmarkExporter(output_dir=args.output_dir)
    exported_paths = exporter.export_all(summaries=summaries, scorecards=scorecards)

    dashboard.console.print(
        f"\n[bold green]Exported Benchmark Artifacts:[/bold green]\n"
        f"  • Leaderboard CSV : [underline]{exported_paths.leaderboard_csv_path}[/underline]\n"
        f"  • Detailed Runs   : [underline]{exported_paths.detailed_runs_csv_path}[/underline]\n"
        f"  • Full JSON Report: [underline]{exported_paths.json_report_path}[/underline]\n"
    )
    return 0


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(async_main(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
