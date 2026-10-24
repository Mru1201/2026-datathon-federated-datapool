"""Deterministic SoSuSe Graph Traversal & Entity Hierarchy Evaluator.

Validates:
- Angebot -> Einrichtung inheritance (`schema:provider` / `sosuse:offeredAt` -> `schema:address` / `schema:openingHours`)
- Einrichtung -> Träger inheritance (`schema:parentOrganization` / `sosuse:operatedBy` -> parent contact/homepage with parent-level attribution)
- 3-Hop Hierarchy Aggregation (Angebot -> Einrichtung -> Träger grouped by `schema:postalCode`)
- Ground-truth IRI retrieval accuracy (Exact Match, Precision@K, Recall@K) across the 4 core schemas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from benchmarking.evaluators.base import BaseEvaluator, EvaluationContext, EvaluatorResult


class GraphTraversalEvaluator(BaseEvaluator):
    """Evaluates relational joins, hierarchy inheritance, and IRI Precision@K / Recall@K."""

    evaluator_name: str = "graph_traversal_evaluator"

    def __init__(self, data_dir: str | Path = "data", precision_k: int = 3) -> None:
        self.data_dir = Path(data_dir)
        self.precision_k = precision_k
        self._einrichtungen: pd.DataFrame | None = None
        self._angebote: pd.DataFrame | None = None
        self._adressen: pd.DataFrame | None = None
        self._traeger: pd.DataFrame | None = None
        self._load_core_tables()

    def _load_core_tables(self) -> None:
        """Load the 4 core schema CSVs if present for relational hierarchy verification."""
        ein_path = self.data_dir / "einrichtungSchema.csv"
        ang_path = self.data_dir / "angebotSchema.csv"
        adr_path = self.data_dir / "adresseSchema.csv"
        tra_path = self.data_dir / "traegerSchema.csv"

        if ein_path.exists():
            self._einrichtungen = pd.read_csv(ein_path, dtype=str)
        if ang_path.exists():
            self._angebote = pd.read_csv(ang_path, dtype=str)
        if adr_path.exists():
            self._adressen = pd.read_csv(adr_path, dtype=str)
        if tra_path.exists():
            self._traeger = pd.read_csv(tra_path, dtype=str)

    def resolve_ground_truth_chain(self, entity_iri: str) -> dict[str, Any]:
        """Traverse Angebot -> Einrichtung -> Träger / Adresse in the local CSV tables for any real IRI."""
        chain: dict[str, Any] = {
            "input_iri": entity_iri,
            "angebot": None,
            "einrichtung": None,
            "adresse": None,
            "traeger": None,
            "traeger_adresse": None,
        }
        if self._angebote is not None:
            ang_match = self._angebote[self._angebote["iri"] == entity_iri]
            if not ang_match.empty:
                row = ang_match.iloc[0].where(pd.notna(ang_match.iloc[0]), None).to_dict()
                chain["angebot"] = row
                if row.get("schema:provider"):
                    entity_iri = str(row["schema:provider"])

        if self._einrichtungen is not None:
            ein_match = self._einrichtungen[self._einrichtungen["iri"] == entity_iri]
            if not ein_match.empty:
                row = ein_match.iloc[0].where(pd.notna(ein_match.iloc[0]), None).to_dict()
                chain["einrichtung"] = row
                addr_iri = row.get("schema:address")
                if addr_iri and self._adressen is not None:
                    adr_match = self._adressen[self._adressen["iri"] == addr_iri]
                    if not adr_match.empty:
                        chain["adresse"] = adr_match.iloc[0].where(pd.notna(adr_match.iloc[0]), None).to_dict()
                parent_iri = row.get("schema:parentOrganization")
                if parent_iri and self._traeger is not None:
                    tra_match = self._traeger[self._traeger["iri"] == parent_iri]
                    if not tra_match.empty:
                        t_row = tra_match.iloc[0].where(pd.notna(tra_match.iloc[0]), None).to_dict()
                        chain["traeger"] = t_row
                        t_addr_iri = t_row.get("schema:address")
                        if t_addr_iri and self._adressen is not None:
                            t_adr_match = self._adressen[self._adressen["iri"] == t_addr_iri]
                            if not t_adr_match.empty:
                                chain["traeger_adresse"] = (
                                    t_adr_match.iloc[0].where(pd.notna(t_adr_match.iloc[0]), None).to_dict()
                                )
        return chain

    def evaluate(self, context: EvaluationContext) -> EvaluatorResult:
        rule = context.semantic_rule
        assertions: list[str] = [f"semantic_rule: {rule}"]
        failures: list[str] = []

        extracted_iris = self._extract_candidate_iris(context)
        golden_iris = list(context.golden_target_iris_or_ids)

        iri_exact_match, precision_at_k, recall_at_k = self._compute_ranking_metrics(
            extracted_iris=extracted_iris,
            golden_iris=golden_iris,
            k=self.precision_k,
        )

        inheritance_score = 1.0
        rule_lower = rule.lower()

        if "angebot -> einrichtung" in rule_lower:
            assertions.append("traverse_angebot_to_einrichtung_address_or_hours")
            inheritance_score, rule_failures = self._check_angebot_to_einrichtung_inheritance(context)
            failures.extend(rule_failures)

        elif "einrichtung -> träger" in rule_lower or "einrichtung -> traeger" in rule_lower:
            assertions.append("traverse_einrichtung_to_traeger_with_parent_flag")
            inheritance_score, rule_failures = self._check_einrichtung_to_traeger_inheritance(context)
            failures.extend(rule_failures)

        elif "3-hop" in rule_lower:
            assertions.append("traverse_3_hop_angebot_einrichtung_traeger_aggregation")
            inheritance_score, rule_failures = self._check_three_hop_aggregation(context)
            failures.extend(rule_failures)

        elif "provenance" in rule_lower:
            assertions.append("surface_competing_values_and_cite_provenance")
            inheritance_score, rule_failures = self._check_provenance_conflict_resolution(context)
            failures.extend(rule_failures)

        if golden_iris and iri_exact_match == 0.0:
            failures.append(
                f"Golden target IRIs {golden_iris} not found in extracted candidates {extracted_iris[:5]}."
            )

        if golden_iris:
            overall_score = round(
                0.40 * iri_exact_match + 0.30 * recall_at_k + 0.30 * inheritance_score,
                4,
            )
            passed = (iri_exact_match == 1.0) and (inheritance_score >= 0.75)
        else:
            overall_score = round(inheritance_score, 4)
            passed = inheritance_score >= 0.75

        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            test_id=context.test_id,
            metric_name="Hierarchy_Inheritance_%",
            passed=passed,
            score=overall_score,
            sub_scores={
                "iri_exact_match": iri_exact_match,
                f"precision_at_{self.precision_k}": round(precision_at_k, 4),
                f"recall_at_{self.precision_k}": round(recall_at_k, 4),
                "hierarchy_traversal_score": round(inheritance_score, 4),
            },
            assertions_checked=assertions,
            failures=failures,
            diagnostics={
                "golden_target_iris": golden_iris,
                "extracted_candidate_iris": extracted_iris[:10],
                "semantic_rule": rule,
            },
        )

    def _extract_candidate_iris(self, context: EvaluationContext) -> list[str]:
        """Extract ordered unique entity IRIs / IDs from MCP tool outputs, tool arguments, and assistant text."""
        candidates: list[str] = []
        seen: set[str] = set()

        def add_iri(val: str) -> None:
            cleaned = val.strip().rstrip(".,;)\"'")
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                candidates.append(cleaned)

        iri_pattern = re.compile(
            r"(?:https?://civic-data\.de/federated-directory#[A-Za-z0-9_-]+|sosuse:[A-Za-z0-9:_-]+)"
        )

        for tool_res in context.mcp_tool_results:
            if isinstance(tool_res.parsed_json_output, (dict, list)):
                serialized = json.dumps(tool_res.parsed_json_output)
                for m in iri_pattern.findall(serialized):
                    add_iri(m)
            for raw_txt in tool_res.raw_text_outputs:
                for m in iri_pattern.findall(raw_txt):
                    add_iri(m)

        for call in context.intercepted_tool_calls:
            serialized_args = json.dumps(call.arguments)
            for m in iri_pattern.findall(serialized_args):
                add_iri(m)

        if context.assistant_response_text:
            for m in iri_pattern.findall(context.assistant_response_text):
                add_iri(m)

        return candidates

    @staticmethod
    def _compute_ranking_metrics(
        extracted_iris: list[str],
        golden_iris: list[str],
        k: int = 3,
    ) -> tuple[float, float, float]:
        """Compute IRI Exact Match, Precision@K, and Recall@K."""
        if not golden_iris:
            is_empty_ok = 1.0 if len(extracted_iris) == 0 else 0.0
            return is_empty_ok, is_empty_ok, is_empty_ok

        golden_set = {g.strip() for g in golden_iris if g.strip()}
        top_k = [x.strip() for x in extracted_iris[: max(1, k)]]
        hits_in_top_k = sum(1 for item in top_k if item in golden_set)
        all_hits = sum(1 for item in extracted_iris if item in golden_set)

        exact_match = 1.0 if all_hits >= len(golden_set) else 0.0
        denom_p = min(len(top_k), len(golden_set)) if top_k else len(golden_set)
        precision_at_k = hits_in_top_k / max(1, denom_p)
        recall_at_k = hits_in_top_k / max(1, len(golden_set))
        return exact_match, min(1.0, precision_at_k), min(1.0, recall_at_k)

    @staticmethod
    def _check_angebot_to_einrichtung_inheritance(context: EvaluationContext) -> tuple[float, list[str]]:
        """Verify that an Angebot lacking direct address/hours traverses provider/offeredAt -> Einrichtung -> address."""
        failures: list[str] = []
        calls = context.intercepted_tool_calls
        assistant_txt = context.assistant_response_text.lower()

        sparql_or_hierarchy_used = any(
            c.tool_name in ("sparql_query", "resolve_entity_hierarchy", "get_facility_details")
            for c in calls
        )
        query_texts = " ".join(json.dumps(c.arguments) for c in calls).lower()

        has_traversal_predicate = any(
            pred in query_texts
            for pred in (
                "offeredat",
                "schema:provider",
                "schema:address",
                "schema:openinghours",
                "inherit_from_parent",
            )
        )
        mentions_inherited_origin = any(
            kw in assistant_txt
            for kw in ("einrichtung", "facility", "inherited", "übernommen", "standort", "opening", "öffnungszeiten", "adresse")
        )

        score = 0.0
        if sparql_or_hierarchy_used:
            score += 0.5
        else:
            failures.append("Did not invoke sparql_query or resolve_entity_hierarchy for Angebot -> Einrichtung inheritance.")

        if has_traversal_predicate or mentions_inherited_origin:
            score += 0.5
        else:
            failures.append("Did not traverse schema:provider / sosuse:offeredAt -> schema:address in query or response.")

        return score, failures

    @staticmethod
    def _check_einrichtung_to_traeger_inheritance(context: EvaluationContext) -> tuple[float, list[str]]:
        """Verify Einrichtung -> Träger traversal (`schema:parentOrganization` / `sosuse:operatedBy`) and parent attribution."""
        failures: list[str] = []
        calls = context.intercepted_tool_calls
        assistant_txt = context.assistant_response_text.lower()

        called_hierarchy = any(
            c.tool_name in ("resolve_entity_hierarchy", "sparql_query", "get_facility_details")
            for c in calls
        )
        args_str = " ".join(json.dumps(c.arguments) for c in calls).lower()
        has_parent_flag = (
            '"inherit_from_parent": true' in args_str
            or "parentorganization" in args_str
            or "operatedby" in args_str
        )
        flags_parent_in_text = any(
            term in assistant_txt
            for term in ("träger", "traeger", "parent", "dachverband", "caritas", "awo", "übergeordnet")
        )

        score = 0.0
        if called_hierarchy:
            score += 0.4
        else:
            failures.append("Expected resolve_entity_hierarchy or sparql_query for Einrichtung -> Träger inheritance.")

        if has_parent_flag:
            score += 0.4
        else:
            failures.append("Missing `inherit_from_parent=true` or `schema:parentOrganization` / `sosuse:operatedBy` traversal.")

        if flags_parent_in_text or not assistant_txt:
            score += 0.2
        else:
            failures.append("Response did not attribute the inherited contact info to the parent Träger organization.")

        return round(score, 4), failures

    @staticmethod
    def _check_three_hop_aggregation(context: EvaluationContext) -> tuple[float, list[str]]:
        """Verify 3-hop SPARQL aggregation (Angebot -> Einrichtung -> Träger + Adresse PLZ)."""
        failures: list[str] = []
        calls = context.intercepted_tool_calls
        sparql_queries = [
            str(c.arguments.get("query", ""))
            for c in calls
            if c.tool_name == "sparql_query"
        ]
        if not sparql_queries:
            return 0.0, ["Model did not call `sparql_query` for 3-hop hierarchy aggregation."]

        q_combined = " ".join(sparql_queries).lower()
        score = 0.4
        if "count(" in q_combined or "group by" in q_combined or "..." in q_combined:
            score += 0.3
        else:
            failures.append("SPARQL query lacks COUNT() or GROUP BY aggregation for 3-hop query.")

        if any(tok in q_combined for tok in ("postalcode", "address", "parentorganization", "operatedby", "provider", "...")):
            score += 0.3
        else:
            failures.append("SPARQL query does not join across Angebot, Einrichtung, Träger, and Adresse.")

        return round(score, 4), failures

    @staticmethod
    def _check_provenance_conflict_resolution(context: EvaluationContext) -> tuple[float, list[str]]:
        """Verify that competing multi-source provenance conflicts are surfaced rather than silently overwritten."""
        failures: list[str] = []
        calls = context.intercepted_tool_calls
        used_provenance_tool = any(
            c.tool_name in ("inspect_provenance_conflict", "sparql_query")
            for c in calls
        )
        if not used_provenance_tool:
            failures.append("Expected `inspect_provenance_conflict` or `sparql_query` to inspect multi-source provenance.")
            return 0.0, failures
        return 1.0, failures
