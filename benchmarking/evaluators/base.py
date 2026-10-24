"""BaseEvaluator interface and strict Pydantic evaluation models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from benchmarking.core.mcp_client import MCPToolExecutionResult
from benchmarking.core.model_adapter import InterceptedToolCall, ModelInvocationResult


class EvaluationContext(BaseModel):
    """Input payload passed to every deterministic evaluator for a single test case."""

    model_config = ConfigDict(extra="allow")

    test_id: str = Field(..., description="Unique evaluation test case ID (e.g., 'Q01', 'P001')")
    prompt: str = Field(..., description="Original user prompt sent to the model")
    expected_tool: str = Field(..., description="Expected MCP tool name")
    expected_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Expected JSON arguments for the MCP tool call",
    )
    golden_target_iris_or_ids: list[str] = Field(
        default_factory=list,
        description="Expected ground-truth IRIs or IDs (empty list for zero-result negative tests)",
    )
    demographic_or_language: str = Field(default="Standard German | General")
    section_category: str = Field(default="1. Citizen Local & Semantic Search")
    semantic_rule: str = Field(default="Direct Facility Lookup")
    grading_metric: str = Field(default="IRI_Exact_Match + Precision@3")
    regex_or_ast_assertion: str | None = Field(default=None)
    known_data_trap: str | None = Field(default=None)
    pass_criteria: str = Field(default="")

    model_invocation: ModelInvocationResult | None = Field(
        default=None,
        description="Full telemetry and output from the LiteLLM model adapter",
    )
    mcp_tool_results: list[MCPToolExecutionResult] = Field(
        default_factory=list,
        description="Tool execution results returned by the MCP server (or fault injector)",
    )

    @property
    def intercepted_tool_calls(self) -> list[InterceptedToolCall]:
        """Convenience accessor for tool calls intercepted during model invocation."""
        if self.model_invocation is not None:
            return self.model_invocation.intercepted_tool_calls
        return []

    @property
    def assistant_response_text(self) -> str:
        """Convenience accessor for final assistant text response."""
        if self.model_invocation is not None and self.model_invocation.assistant_content:
            return self.model_invocation.assistant_content
        return ""


class EvaluatorResult(BaseModel):
    """Structured Pydantic evaluation result returned by all deterministic evaluators."""

    model_config = ConfigDict(extra="forbid")

    evaluator_name: str = Field(..., description="Identifier of the evaluator producing this result")
    test_id: str = Field(..., description="Evaluation test case ID")
    metric_name: str = Field(..., description="Primary grading metric evaluated")
    passed: bool = Field(..., description="Binary pass/fail determination")
    score: float = Field(..., ge=0.0, le=1.0, description="Normalized continuous score in [0.0, 1.0]")
    sub_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Granular component scores (e.g., precision_at_k, recall_at_k, parameter_f1)",
    )
    assertions_checked: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list, description="Specific deterministic failure reasons")
    diagnostics: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured metadata for audit logs and error analysis",
    )


class BaseEvaluator(ABC):
    """Abstract base class for all deterministic MCP benchmark evaluators."""

    evaluator_name: str = "base_evaluator"

    @abstractmethod
    def evaluate(self, context: EvaluationContext) -> EvaluatorResult:
        """Deterministically score a single `EvaluationContext` and return an `EvaluatorResult`."""
        raise NotImplementedError
