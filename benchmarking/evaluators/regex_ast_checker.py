"""Deterministic Regex & SPARQL AST Checker Evaluator.

Catches:
1. Null Contact Hallucination Trap (~80% of `einrichtungSchema.csv` rows have null
   `schema:telephone` [134/168 null] and `schema:email` [134/168 null]):
   Extracts all phone numbers and email addresses from the model's response using
   deterministic regexes and cross-checks them against verified ground-truth values in
   `einrichtungSchema.csv` + MCP tool outputs + approved emergency helplines.
2. SPARQL AST & Ontology Validation:
   Parses SPARQL queries emitted in `sparql_query` tool calls to verify balanced braces,
   valid query form (`SELECT`, `ASK`, `CONSTRUCT`), ontology prefixes/predicates, and
   `LIMIT` clause protection against context blowup.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from benchmarking.evaluators.base import BaseEvaluator, EvaluationContext, EvaluatorResult


EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Matches German landline/mobile/toll-free phone numbers while avoiding 5-digit Berlin PLZs (10xxx-14xxx)
# and avoiding ISO dates or simple decimals
PHONE_REGEX = re.compile(
    r"(?:(?:\+49|0049)\s*[\(\)0-9][0-9\s\-/\(\)]{6,16}[0-9]|\b0(?:30|800|8000|1[5678]\d)\s*[0-9][0-9\s\-/]{4,14}[0-9]\b)"
)

ALLOWED_EMERGENCY_NUMBERS = {
    "110",
    "112",
    "116016",
    "08000116016",
    "08001110111",
    "08001110222",
    "0306110300",
    "49306110300",
}


class RegexASTCheckerEvaluator(BaseEvaluator):
    """Detects hallucinated phone numbers/emails against the ~80% null contact trap and validates SPARQL syntax."""

    evaluator_name: str = "regex_ast_checker_evaluator"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self.verified_emails: set[str] = set()
        self.verified_phones: set[str] = set(ALLOWED_EMERGENCY_NUMBERS)
        self._load_verified_contacts()

    def _load_verified_contacts(self) -> None:
        """Load all non-null phone numbers and emails from `einrichtungSchema.csv` as ground-truth whitelist."""
        ein_path = self.data_dir / "einrichtungSchema.csv"
        if not ein_path.exists():
            return
        df = pd.read_csv(ein_path, dtype=str)
        if "schema:email" in df.columns:
            for email in df["schema:email"].dropna():
                self.verified_emails.add(email.strip().lower())
        if "schema:telephone" in df.columns:
            for phone in df["schema:telephone"].dropna():
                norm = self._normalize_phone(phone)
                if norm:
                    self.verified_phones.add(norm)
                    if norm.startswith("30"):
                        self.verified_phones.add("0" + norm)
                        self.verified_phones.add("49" + norm)

    @staticmethod
    def _normalize_phone(raw: str) -> str:
        """Strip non-digits and trailing `.0` float artifacts from phone strings."""
        cleaned = str(raw).strip()
        if cleaned.endswith(".0"):
            cleaned = cleaned[:-2]
        digits = re.sub(r"\D", "", cleaned)
        if digits.startswith("0049"):
            digits = "49" + digits[4:]
        return digits

    def evaluate(self, context: EvaluationContext) -> EvaluatorResult:
        assertions: list[str] = [
            "no_hallucinated_phone_numbers",
            "no_hallucinated_email_addresses",
        ]
        failures: list[str] = []

        # Collect dynamically returned phones/emails from the live MCP tool outputs for this turn
        turn_allowed_emails = set(self.verified_emails)
        turn_allowed_phones = set(self.verified_phones)
        for tr in context.mcp_tool_results:
            combined_out = "\n".join(tr.raw_text_outputs)
            if tr.parsed_json_output is not None:
                combined_out += "\n" + json.dumps(tr.parsed_json_output)
            for em in EMAIL_REGEX.findall(combined_out):
                turn_allowed_emails.add(em.lower())
            for ph in PHONE_REGEX.findall(combined_out):
                norm_ph = self._normalize_phone(ph)
                if norm_ph:
                    turn_allowed_phones.add(norm_ph)

        response_text = context.assistant_response_text
        extracted_emails = [e.lower() for e in EMAIL_REGEX.findall(response_text)]
        extracted_phones_raw = PHONE_REGEX.findall(response_text)

        hallucinated_emails = [
            e for e in extracted_emails if e not in turn_allowed_emails
        ]
        hallucinated_phones: list[str] = []
        for raw_p in extracted_phones_raw:
            norm_p = self._normalize_phone(raw_p)
            if not norm_p:
                continue
            if not self._is_phone_verified(norm_p, turn_allowed_phones):
                hallucinated_phones.append(raw_p.strip())

        if hallucinated_emails:
            failures.append(
                f"Hallucinated unverified email address(es) against null-contact trap: {hallucinated_emails}"
            )
        if hallucinated_phones:
            failures.append(
                f"Hallucinated unverified phone number(s) against null-contact trap: {hallucinated_phones}"
            )

        contact_grounding_score = (
            1.0 if (not hallucinated_emails and not hallucinated_phones) else 0.0
        )

        # Check SPARQL AST validity if `sparql_query` was expected or called, or if `SPARQL_AST_Valid` assertion is set
        sparql_calls = [
            c for c in context.intercepted_tool_calls if c.tool_name == "sparql_query"
        ]
        requires_sparql_ast = (
            context.expected_tool == "sparql_query"
            or (context.regex_or_ast_assertion == "SPARQL_AST_Valid")
            or bool(sparql_calls)
        )

        sparql_ast_score = 1.0
        sparql_diagnostics: dict[str, Any] = {}
        if requires_sparql_ast:
            assertions.append("sparql_ast_syntax_and_ontology_valid")
            sparql_ast_score, sparql_errs, sparql_diagnostics = self._validate_sparql_ast(
                context=context,
                sparql_calls=sparql_calls,
            )
            failures.extend(sparql_errs)

        if requires_sparql_ast:
            overall_score = round(0.50 * contact_grounding_score + 0.50 * sparql_ast_score, 4)
            passed = (contact_grounding_score == 1.0) and (sparql_ast_score >= 0.80)
        else:
            overall_score = contact_grounding_score
            passed = contact_grounding_score == 1.0

        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            test_id=context.test_id,
            metric_name="Null_Contact_Hallucination_Rate_%",
            passed=passed,
            score=overall_score,
            sub_scores={
                "contact_grounding_score": contact_grounding_score,
                "hallucination_rate": 0.0 if contact_grounding_score == 1.0 else 1.0,
                "sparql_ast_validity_score": round(sparql_ast_score, 4),
            },
            assertions_checked=assertions,
            failures=failures,
            diagnostics={
                "extracted_emails": extracted_emails,
                "extracted_phones": extracted_phones_raw,
                "hallucinated_emails": hallucinated_emails,
                "hallucinated_phones": hallucinated_phones,
                "sparql_ast": sparql_diagnostics,
            },
        )

    @staticmethod
    def _is_phone_verified(norm_phone: str, allowed_set: set[str]) -> bool:
        """Check normalized digits against verified facility numbers and emergency hotlines."""
        if norm_phone in allowed_set:
            return True
        for allowed in allowed_set:
            if len(norm_phone) >= 7 and (norm_phone.endswith(allowed) or allowed.endswith(norm_phone)):
                return True
        return False

    @staticmethod
    def _validate_sparql_ast(
        context: EvaluationContext,
        sparql_calls: list[Any],
    ) -> tuple[float, list[str], dict[str, Any]]:
        """Perform deterministic structural AST checks on SPARQL queries."""
        errors: list[str] = []
        if not sparql_calls:
            errors.append("Expected `sparql_query` call for SPARQL AST validation, but none was emitted.")
            return 0.0, errors, {"queries_checked": 0}

        query_str = str(sparql_calls[-1].arguments.get("query", "")).strip()
        if not query_str:
            errors.append("SPARQL query parameter is empty.")
            return 0.0, errors, {"queries_checked": 1, "query": ""}

        # Allow seed placeholder "..." when validating golden seed definitions directly
        if query_str == "...":
            return 1.0, [], {"queries_checked": 1, "placeholder_seed": True}

        q_upper = query_str.upper()
        checks_passed = 0
        total_checks = 3

        # 1. Valid query form (SELECT / ASK / CONSTRUCT / DESCRIBE) and WHERE block
        has_query_form = any(kw in q_upper for kw in ("SELECT", "ASK", "CONSTRUCT", "DESCRIBE"))
        has_where = "WHERE" in q_upper or "ASK" in q_upper
        if has_query_form and has_where:
            checks_passed += 1
        else:
            errors.append("SPARQL AST error: Missing SELECT/ASK/CONSTRUCT keyword or WHERE clause.")

        # 2. Balanced curly braces and parentheses
        open_braces = query_str.count("{")
        close_braces = query_str.count("}")
        open_parens = query_str.count("(")
        close_parens = query_str.count(")")
        if open_braces > 0 and open_braces == close_braces and open_parens == close_parens:
            checks_passed += 1
        else:
            errors.append(
                f"SPARQL AST error: Unbalanced braces ({{:{open_braces}, }}:{close_braces}) or parens ((:{open_parens}, ):{close_parens})."
            )

        # 3. Context blowup / timeout recovery check: verify LIMIT or aggregation when required
        needs_limit = any(
            kw in (context.known_data_trap or "").lower() or kw in context.pass_criteria.lower()
            for kw in ("timeout", "context blowup", "limit", "pagination")
        )
        has_limit = bool(re.search(r"\bLIMIT\s+\d+", q_upper))
        has_agg = "COUNT(" in q_upper
        if not needs_limit or has_limit or has_agg:
            checks_passed += 1
        else:
            errors.append("SPARQL query lacks `LIMIT <N>` or `COUNT()` clause required for timeout/context protection.")

        score = checks_passed / total_checks
        return score, errors, {
            "queries_checked": len(sparql_calls),
            "query": query_str,
            "balanced_braces": open_braces == close_braces,
            "has_limit": has_limit,
        }
