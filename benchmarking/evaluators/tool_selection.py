"""Deterministic Tool Selection & Parameter Schema Validation Evaluator.

Scores:
1. Tool choice accuracy (whether the model invoked `expected_tool`).
2. JSON schema compliance against `benchmarking/config/tools_schema.json` (detecting
   unknown parameters, missing required fields, and type mismatches).
3. Parameter value accuracy (comparing model-emitted parameters against
   `expected_parameters` with semantic normalization for Berlin districts, PLZs,
   multilingual category codes, and geographic coordinates).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from benchmarking.core.mcp_client import ToolsSchemaSpec
from benchmarking.evaluators.base import BaseEvaluator, EvaluationContext, EvaluatorResult


class ToolSelectionEvaluator(BaseEvaluator):
    """Scores MCP tool selection accuracy, JSON schema compliance, and argument matching."""

    evaluator_name: str = "tool_selection_evaluator"

    def __init__(self, schema_path: str | Path = "benchmarking/config/tools_schema.json") -> None:
        self.tools_spec = ToolsSchemaSpec.from_json_file(schema_path)
        self._tool_schemas = {t.name: t.inputSchema for t in self.tools_spec.tools}

    def evaluate(self, context: EvaluationContext) -> EvaluatorResult:
        calls = context.intercepted_tool_calls
        assertions: list[str] = [
            f"expect_tool == '{context.expected_tool}'",
            "json_schema_valid == True",
            "expected_parameters_match",
        ]
        failures: list[str] = []

        if not calls:
            failures.append(f"Model emitted 0 tool calls; expected '{context.expected_tool}'.")
            return EvaluatorResult(
                evaluator_name=self.evaluator_name,
                test_id=context.test_id,
                metric_name="Tool_Selection_Accuracy_%",
                passed=False,
                score=0.0,
                sub_scores={
                    "tool_name_accuracy": 0.0,
                    "schema_validity": 0.0,
                    "parameter_match_score": 0.0,
                },
                assertions_checked=assertions,
                failures=failures,
                diagnostics={"called_tools": []},
            )

        called_names = [c.tool_name for c in calls]
        matching_call = next((c for c in calls if c.tool_name == context.expected_tool), None)
        primary_call = matching_call if matching_call is not None else calls[0]

        tool_name_acc = 1.0 if matching_call is not None else 0.0
        if tool_name_acc == 0.0:
            failures.append(
                f"Expected tool '{context.expected_tool}', but model called {called_names}."
            )

        schema_valid_score, schema_errors = self._validate_against_json_schema(
            tool_name=primary_call.tool_name,
            arguments=primary_call.arguments,
            parse_error=primary_call.parse_error,
        )
        failures.extend(schema_errors)

        param_score, param_errors, param_details = self._score_parameters(
            expected_params=context.expected_parameters,
            actual_params=primary_call.arguments,
            all_calls=[c.arguments for c in calls if c.tool_name == context.expected_tool],
        )
        failures.extend(param_errors)

        composite_score = round(
            0.50 * tool_name_acc + 0.20 * schema_valid_score + 0.30 * param_score,
            4,
        )
        passed = (tool_name_acc == 1.0) and (schema_valid_score == 1.0) and (param_score >= 0.75)

        return EvaluatorResult(
            evaluator_name=self.evaluator_name,
            test_id=context.test_id,
            metric_name="Tool_Selection_Accuracy_%",
            passed=passed,
            score=composite_score,
            sub_scores={
                "tool_name_accuracy": tool_name_acc,
                "schema_validity": schema_valid_score,
                "parameter_match_score": round(param_score, 4),
            },
            assertions_checked=assertions,
            failures=failures,
            diagnostics={
                "called_tools": called_names,
                "selected_call_arguments": primary_call.arguments,
                "expected_parameters": context.expected_parameters,
                "parameter_comparison": param_details,
            },
        )

    def _validate_against_json_schema(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        parse_error: str | None,
    ) -> tuple[float, list[str]]:
        """Validate tool call arguments against `tools_schema.json`."""
        errors: list[str] = []
        if parse_error:
            errors.append(f"Malformed JSON in tool arguments: {parse_error}")
            return 0.0, errors

        schema = self._tool_schemas.get(tool_name)
        if schema is None:
            errors.append(f"Tool '{tool_name}' is not defined in tools_schema.json.")
            return 0.0, errors

        properties: dict[str, Any] = schema.get("properties", {})
        required: list[str] = schema.get("required", [])
        additional_allowed: bool = schema.get("additionalProperties", True)

        for req_key in required:
            if req_key not in arguments or arguments[req_key] is None:
                errors.append(f"Missing required parameter '{req_key}' for tool '{tool_name}'.")

        if not additional_allowed:
            for arg_key in arguments:
                if arg_key not in properties:
                    errors.append(f"Unexpected parameter '{arg_key}' not in schema for '{tool_name}'.")

        for arg_key, arg_val in arguments.items():
            if arg_key not in properties or arg_val is None:
                continue
            prop_schema = properties[arg_key]
            if not self._check_json_type(arg_val, prop_schema):
                errors.append(
                    f"Parameter '{arg_key}' value {arg_val!r} failed schema type constraint {prop_schema}."
                )

        return (1.0 if not errors else 0.0), errors

    @classmethod
    def _check_json_type(cls, value: Any, prop_schema: dict[str, Any]) -> bool:
        """Check whether a Python value conforms to a JSON Schema property definition."""
        if "anyOf" in prop_schema:
            return any(cls._check_json_type(value, sub) for sub in prop_schema["anyOf"])

        expected_type = prop_schema.get("type")
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "array":
            if not isinstance(value, list):
                return False
            item_schema = prop_schema.get("items")
            if isinstance(item_schema, dict):
                return all(cls._check_json_type(v, item_schema) for v in value)
            return True
        if expected_type == "object":
            return isinstance(value, dict)
        return True

    def _score_parameters(
        self,
        expected_params: dict[str, Any],
        actual_params: dict[str, Any],
        all_calls: list[dict[str, Any]],
    ) -> tuple[float, list[str], dict[str, bool]]:
        """Compare expected parameters against actual model arguments with semantic normalization."""
        if not expected_params:
            return 1.0, [], {}

        errors: list[str] = []
        matched_map: dict[str, bool] = {}

        for key, exp_val in expected_params.items():
            if key == "query" and exp_val == "...":
                has_non_empty_query = isinstance(actual_params.get("query"), str) and bool(
                    actual_params["query"].strip()
                )
                matched_map[key] = has_non_empty_query
                if not has_non_empty_query:
                    errors.append("Expected non-empty SPARQL 'query' string.")
                continue

            act_val = actual_params.get(key)
            is_match = self._values_semantically_equal(key, exp_val, act_val)

            if not is_match and isinstance(exp_val, list) and len(all_calls) > 1:
                combined_vals = [c.get(key) for c in all_calls if key in c]
                is_match = self._values_semantically_equal(key, exp_val, combined_vals)

            matched_map[key] = is_match
            if not is_match:
                errors.append(
                    f"Parameter '{key}' mismatch: expected {exp_val!r}, got {act_val!r}."
                )

        score = sum(1.0 for v in matched_map.values() if v) / len(expected_params)
        return score, errors, matched_map

    @classmethod
    def _values_semantically_equal(cls, key: str, expected: Any, actual: Any) -> bool:
        """Compare expected and actual parameter values with domain-specific tolerance."""
        if actual is None:
            return False

        if isinstance(expected, bool):
            return isinstance(actual, bool) and expected == actual

        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            if not isinstance(actual, (int, float)) or isinstance(actual, bool):
                return False
            if key in ("lat", "lon"):
                return math.isclose(float(expected), float(actual), abs_tol=0.015)
            return math.isclose(float(expected), float(actual), rel_tol=0.1)

        if isinstance(expected, list):
            exp_set = {cls._norm_str(x) for x in expected}
            if isinstance(actual, list):
                act_set = {cls._norm_str(x) for x in actual}
                return exp_set.issubset(act_set)
            if isinstance(actual, str):
                act_parts = {cls._norm_str(x) for x in actual.split(",")}
                return exp_set.issubset(act_parts)
            return False

        exp_str = cls._norm_str(expected)
        act_str = cls._norm_str(actual)
        if exp_str == act_str:
            return True

        if key == "locality":
            exp_clean = exp_str.removeprefix("berlin-").removeprefix("berlin ").strip()
            act_clean = act_str.removeprefix("berlin-").removeprefix("berlin ").strip()
            if exp_clean and exp_clean == act_clean:
                return True

        if key in ("category", "audience"):
            if exp_str in act_str or act_str in exp_str:
                return True

        return False

    @staticmethod
    def _norm_str(val: Any) -> str:
        return str(val).strip().lower()
