"""Async LiteLLM Model Adapter for the MCP Benchmarking Suite.

Sends evaluation prompts and MCP tool schemas to Frontier, Fast, and Local models
via LiteLLM. Records:
- Token counts (prompt_tokens, completion_tokens, total_tokens)
- Time-To-First-Token (TTFT in ms)
- Total roundtrip latency (ms)
- Intercepted tool calls (name, parsed arguments, raw arguments string, call ID)
- Estimated inference cost (USD)
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Literal

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
import litellm
import yaml
from pydantic import BaseModel, ConfigDict, Field


DEFAULT_SYSTEM_PROMPT = (
    "You are an AI assistant connected to the German Welfare Federated Data Pool "
    "(Föderierter Datenpool für soziale Unterstützungsangebote) via the Model Context "
    "Protocol (MCP). Use the provided MCP tools to accurately query facilities "
    "(Einrichtungen), services (Angebote), addresses (Adressen), and providers (Träger). "
    "Normalize non-German queries or regional dialects into standard German welfare "
    "categories and locality names when calling search tools. Never fabricate phone "
    "numbers, addresses, or non-existent facilities."
)


class ModelEntryConfig(BaseModel):
    """Strict Pydantic configuration for a single LLM in `models.yaml`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique benchmark identifier (e.g., 'claude-3-5-sonnet')")
    name: str = Field(..., description="Human-readable display name")
    litellm_model: str = Field(..., description="LiteLLM provider/model string (e.g., 'openai/gpt-4o')")
    provider: str = Field(..., description="Underlying provider name")
    tier: Literal["frontier", "fast", "local"] = Field(..., description="Model tier classification")
    api_base: str | None = Field(default=None, description="Optional custom endpoint for local vLLM/Ollama")
    api_key_env: str | None = Field(default=None, description="Optional env var name for API key")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0)
    timeout_seconds: float = Field(default=60.0, gt=0)
    supports_tool_choice: bool = Field(default=True)
    cost_per_1k_input_usd: float = Field(default=0.0, ge=0.0)
    cost_per_1k_output_usd: float = Field(default=0.0, ge=0.0)


class ModelTierGroup(BaseModel):
    """Group of models belonging to a specific performance/cost tier."""

    model_config = ConfigDict(extra="forbid")

    description: str
    models: list[ModelEntryConfig] = Field(default_factory=list)


class ModelsRegistryConfig(BaseModel):
    """Top-level configuration parsed from `benchmarking/config/models.yaml`."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    default_tier: Literal["frontier", "fast", "local"] = "frontier"
    tiers: dict[Literal["frontier", "fast", "local"], ModelTierGroup]

    @classmethod
    def from_yaml(cls, path: str | Path = "benchmarking/config/models.yaml") -> ModelsRegistryConfig:
        """Load and validate models.yaml."""
        file_path = Path(path)
        with file_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def get_model(self, model_id_or_name: str) -> ModelEntryConfig:
        """Look up a model configuration by its `id`, `name`, or `litellm_model`."""
        target = model_id_or_name.strip().lower()
        for tier_group in self.tiers.values():
            for m in tier_group.models:
                if target in (m.id.lower(), m.name.lower(), m.litellm_model.lower()):
                    return m
        raise KeyError(f"Model '{model_id_or_name}' not found in models.yaml registry.")

    def list_all_models(self, tier: Literal["frontier", "fast", "local"] | None = None) -> list[ModelEntryConfig]:
        """Return all registered models, optionally filtered by tier."""
        if tier is not None:
            return list(self.tiers[tier].models)
        all_models: list[ModelEntryConfig] = []
        for group in self.tiers.values():
            all_models.extend(group.models)
        return all_models


class RetryPolicyConfig(BaseModel):
    """Retry policy settings parsed from `benchmarking/config/eval_config.yaml`."""

    model_config = ConfigDict(extra="ignore")

    max_retries: int = Field(default=3, ge=0)
    initial_backoff_seconds: float = Field(default=1.0, gt=0)
    max_backoff_seconds: float = Field(default=16.0, gt=0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    jitter: bool = Field(default=True)

    @classmethod
    def from_eval_config(cls, path: str | Path = "benchmarking/config/eval_config.yaml") -> RetryPolicyConfig:
        """Load retry policy from eval_config.yaml."""
        file_path = Path(path)
        with file_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data.get("retry_policy", {}))


class InterceptedToolCall(BaseModel):
    """Structured representation of an MCP tool call emitted by the LLM."""

    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(..., description="Tool call identifier generated by the LLM")
    tool_name: str = Field(..., description="Name of the MCP tool invoked")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Parsed JSON dictionary of tool arguments")
    raw_arguments_json: str = Field(default="{}", description="Raw JSON string returned by the model")
    parse_error: str | None = Field(
        default=None,
        description="Populated if the model emitted malformed JSON for tool arguments",
    )


class TokenUsageMetrics(BaseModel):
    """Token consumption and cost metrics for a single model invocation."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)


class ModelInvocationResult(BaseModel):
    """Complete telemetry and output record from an async LiteLLM evaluation turn."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    model_name: str
    litellm_model: str
    tier: Literal["frontier", "fast", "local"]
    success: bool
    assistant_content: str | None = None
    intercepted_tool_calls: list[InterceptedToolCall] = Field(default_factory=list)
    usage: TokenUsageMetrics = Field(default_factory=TokenUsageMetrics)
    ttft_ms: float = Field(..., ge=0.0, description="Time to first token in milliseconds")
    roundtrip_latency_ms: float = Field(..., ge=0.0, description="Total end-to-end LLM latency in milliseconds")
    finish_reason: str | None = None
    retries_attempted: int = Field(default=0, ge=0)
    error_message: str | None = None


class LiteLLMModelAdapter:
    """Async LiteLLM wrapper that dispatches evaluation prompts with MCP tool schemas and records telemetry."""

    def __init__(
        self,
        models_registry: ModelsRegistryConfig | None = None,
        retry_policy: RetryPolicyConfig | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self.models_registry = models_registry or ModelsRegistryConfig.from_yaml()
        self.retry_policy = retry_policy or RetryPolicyConfig.from_eval_config()
        self.system_prompt = system_prompt
        litellm.drop_params = True

    async def evaluate_prompt(
        self,
        model_id_or_name: str,
        user_prompt: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = "auto",
        conversation_history: list[dict[str, Any]] | None = None,
        stream_for_ttft: bool = True,
    ) -> ModelInvocationResult:
        """Send an evaluation prompt and MCP tool schemas to the specified model and capture full telemetry.

        Args:
            model_id_or_name: Model ID, name, or LiteLLM string defined in `models.yaml`.
            user_prompt: The user query from the evaluation suite.
            tools: OpenAI-formatted function tool definitions representing the MCP server tools.
            tool_choice: Tool choice policy ('auto', 'required', 'none', or specific function dict).
            conversation_history: Optional prior messages for multi-turn agentic loops.
            stream_for_ttft: If True, uses streaming with `stream_options={'include_usage': True}` to
                measure exact Time-To-First-Token (TTFT) while reconstructing full tool calls and usage.
        """
        model_cfg = self.models_registry.get_model(model_id_or_name)

        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_prompt})

        return await self.invoke_messages(
            model_cfg=model_cfg,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            stream_for_ttft=stream_for_ttft,
        )

    async def invoke_messages(
        self,
        model_cfg: ModelEntryConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = "auto",
        stream_for_ttft: bool = True,
    ) -> ModelInvocationResult:
        """Execute a LiteLLM completion call with retry backoff, TTFT measurement, and tool call interception."""
        attempt = 0
        last_error: Exception | None = None
        overall_start = time.perf_counter()

        while attempt <= self.retry_policy.max_retries:
            call_start = time.perf_counter()
            try:
                if stream_for_ttft:
                    return await self._run_streaming_call(
                        model_cfg=model_cfg,
                        messages=messages,
                        tools=tools,
                        tool_choice=tool_choice,
                        retries_attempted=attempt,
                    )
                return await self._run_non_streaming_call(
                    model_cfg=model_cfg,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    retries_attempted=attempt,
                )
            except Exception as exc:
                last_error = exc
                if attempt >= self.retry_policy.max_retries:
                    break
                backoff = min(
                    self.retry_policy.max_backoff_seconds,
                    self.retry_policy.initial_backoff_seconds * (self.retry_policy.backoff_multiplier ** attempt),
                )
                if self.retry_policy.jitter:
                    backoff *= random.uniform(0.8, 1.2)
                await asyncio.sleep(backoff)
                attempt += 1

        total_latency_ms = (time.perf_counter() - overall_start) * 1000.0
        return ModelInvocationResult(
            model_id=model_cfg.id,
            model_name=model_cfg.name,
            litellm_model=model_cfg.litellm_model,
            tier=model_cfg.tier,
            success=False,
            ttft_ms=total_latency_ms,
            roundtrip_latency_ms=total_latency_ms,
            retries_attempted=attempt,
            error_message=f"{type(last_error).__name__}: {last_error}" if last_error else "Unknown LLM invocation error",
        )

    async def _run_streaming_call(
        self,
        model_cfg: ModelEntryConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
        retries_attempted: int,
    ) -> ModelInvocationResult:
        """Run `litellm.acompletion(..., stream=True)` to capture true TTFT, then rebuild the response."""
        kwargs: dict[str, Any] = {
            "model": model_cfg.litellm_model,
            "messages": messages,
            "temperature": model_cfg.temperature,
            "max_tokens": model_cfg.max_tokens,
            "timeout": model_cfg.timeout_seconds,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if model_cfg.api_base:
            kwargs["api_base"] = model_cfg.api_base
        if tools:
            kwargs["tools"] = tools
            if model_cfg.supports_tool_choice and tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        start_perf = time.perf_counter()
        first_token_perf: float | None = None
        chunks: list[Any] = []

        response_stream = await litellm.acompletion(**kwargs)
        async for chunk in response_stream:
            if first_token_perf is None:
                choices = getattr(chunk, "choices", [])
                if choices:
                    delta = getattr(choices[0], "delta", None)
                    has_content = bool(getattr(delta, "content", None))
                    has_tools = bool(getattr(delta, "tool_calls", None))
                    if has_content or has_tools:
                        first_token_perf = time.perf_counter()
            chunks.append(chunk)

        end_perf = time.perf_counter()
        roundtrip_ms = (end_perf - start_perf) * 1000.0
        ttft_ms = ((first_token_perf - start_perf) * 1000.0) if first_token_perf is not None else roundtrip_ms

        rebuilt = litellm.stream_chunk_builder(chunks, messages=messages)
        return self._parse_completion_response(
            response=rebuilt,
            model_cfg=model_cfg,
            messages=messages,
            ttft_ms=ttft_ms,
            roundtrip_latency_ms=roundtrip_ms,
            retries_attempted=retries_attempted,
        )

    async def _run_non_streaming_call(
        self,
        model_cfg: ModelEntryConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
        retries_attempted: int,
    ) -> ModelInvocationResult:
        """Run `litellm.acompletion(..., stream=False)` and parse tool calls and token metrics."""
        kwargs: dict[str, Any] = {
            "model": model_cfg.litellm_model,
            "messages": messages,
            "temperature": model_cfg.temperature,
            "max_tokens": model_cfg.max_tokens,
            "timeout": model_cfg.timeout_seconds,
            "stream": False,
        }
        if model_cfg.api_base:
            kwargs["api_base"] = model_cfg.api_base
        if tools:
            kwargs["tools"] = tools
            if model_cfg.supports_tool_choice and tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        start_perf = time.perf_counter()
        response = await litellm.acompletion(**kwargs)
        end_perf = time.perf_counter()
        roundtrip_ms = (end_perf - start_perf) * 1000.0

        return self._parse_completion_response(
            response=response,
            model_cfg=model_cfg,
            messages=messages,
            ttft_ms=roundtrip_ms,
            roundtrip_latency_ms=roundtrip_ms,
            retries_attempted=retries_attempted,
        )

    def _parse_completion_response(
        self,
        response: Any,
        model_cfg: ModelEntryConfig,
        messages: list[dict[str, Any]],
        ttft_ms: float,
        roundtrip_latency_ms: float,
        retries_attempted: int,
    ) -> ModelInvocationResult:
        """Extract assistant content, intercepted tool calls, and token usage from a LiteLLM response."""
        choices = getattr(response, "choices", [])
        if not choices:
            return ModelInvocationResult(
                model_id=model_cfg.id,
                model_name=model_cfg.name,
                litellm_model=model_cfg.litellm_model,
                tier=model_cfg.tier,
                success=False,
                ttft_ms=ttft_ms,
                roundtrip_latency_ms=roundtrip_latency_ms,
                retries_attempted=retries_attempted,
                error_message="Model returned empty choices list.",
            )

        first_choice = choices[0]
        finish_reason = getattr(first_choice, "finish_reason", None)
        msg = getattr(first_choice, "message", None)
        content = getattr(msg, "content", None) if msg is not None else None
        raw_tool_calls = getattr(msg, "tool_calls", None) if msg is not None else None

        intercepted_calls: list[InterceptedToolCall] = []
        if raw_tool_calls:
            for idx, tc in enumerate(raw_tool_calls):
                call_id = getattr(tc, "id", None) or (tc.get("id") if isinstance(tc, dict) else f"call_{idx}")
                fn_obj = getattr(tc, "function", None) or (tc.get("function") if isinstance(tc, dict) else None)
                if fn_obj is None:
                    continue

                t_name = getattr(fn_obj, "name", None) or (fn_obj.get("name") if isinstance(fn_obj, dict) else "")
                raw_args = getattr(fn_obj, "arguments", None)
                if raw_args is None and isinstance(fn_obj, dict):
                    raw_args = fn_obj.get("arguments", "{}")

                if isinstance(raw_args, dict):
                    parsed_args = raw_args
                    raw_args_str = json.dumps(raw_args, ensure_ascii=False)
                    parse_err = None
                else:
                    raw_args_str = str(raw_args or "{}").strip()
                    try:
                        parsed_val = json.loads(raw_args_str) if raw_args_str else {}
                        if isinstance(parsed_val, dict):
                            parsed_args = parsed_val
                            parse_err = None
                        else:
                            parsed_args = {"_value": parsed_val}
                            parse_err = f"Expected JSON object for tool arguments, got {type(parsed_val).__name__}"
                    except Exception as exc:
                        parsed_args = {}
                        parse_err = f"JSONDecodeError: {exc}"

                intercepted_calls.append(
                    InterceptedToolCall(
                        call_id=str(call_id),
                        tool_name=str(t_name),
                        arguments=parsed_args,
                        raw_arguments_json=raw_args_str,
                        parse_error=parse_err,
                    )
                )

        usage_obj = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0) if usage_obj else 0
        completion_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0) if usage_obj else 0

        if prompt_tokens == 0:
            try:
                prompt_tokens = int(litellm.token_counter(model=model_cfg.litellm_model, messages=messages))
            except Exception:
                prompt_tokens = 0

        if completion_tokens == 0 and (content or intercepted_calls):
            completion_text = (content or "") + "".join(c.raw_arguments_json for c in intercepted_calls)
            try:
                completion_tokens = int(litellm.token_counter(model=model_cfg.litellm_model, text=completion_text))
            except Exception:
                completion_tokens = max(1, len(completion_text) // 4)

        total_tokens = prompt_tokens + completion_tokens
        cost_usd = (
            (prompt_tokens / 1000.0) * model_cfg.cost_per_1k_input_usd
            + (completion_tokens / 1000.0) * model_cfg.cost_per_1k_output_usd
        )

        return ModelInvocationResult(
            model_id=model_cfg.id,
            model_name=model_cfg.name,
            litellm_model=model_cfg.litellm_model,
            tier=model_cfg.tier,
            success=True,
            assistant_content=content,
            intercepted_tool_calls=intercepted_calls,
            usage=TokenUsageMetrics(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=round(cost_usd, 6),
            ),
            ttft_ms=round(ttft_ms, 2),
            roundtrip_latency_ms=round(roundtrip_latency_ms, 2),
            finish_reason=finish_reason,
            retries_attempted=retries_attempted,
        )
