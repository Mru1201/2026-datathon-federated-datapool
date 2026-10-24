"""External MCP Benchmarking Client Connector.

Supports connecting to the target MCP server via:
- Stdio transport (spawning a server script via command line)
- SSE transport (Server-Sent Events endpoint)
- Streamable HTTP transport (MCP HTTP endpoint)

Provides dynamic tool introspection via `list_tools()` and strict schema drift
detection against `benchmarking/config/tools_schema.json`.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Literal

import yaml
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field


class StdioConnectionConfig(BaseModel):
    """Configuration for spawning an MCP server over stdio."""

    model_config = ConfigDict(extra="forbid")

    command: str = Field(..., description="Executable command (e.g., 'python' or '.venv/bin/python')")
    args: list[str] = Field(default_factory=list, description="Command line arguments (e.g., ['server.py'])")
    env: dict[str, str] | None = Field(default=None, description="Optional environment variables")
    cwd: str | None = Field(default=None, description="Working directory for the server process")


class HttpConnectionConfig(BaseModel):
    """Configuration for connecting to a hosted MCP server over SSE or Streamable HTTP."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., description="Endpoint URL (e.g., 'http://localhost:8080/sse' or 'http://localhost:8080/mcp')")
    headers: dict[str, str] | None = Field(default=None, description="Optional HTTP headers (e.g., Authorization)")
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    sse_read_timeout_seconds: float = Field(default=300.0, gt=0)


class MCPConnectionConfig(BaseModel):
    """Unified connection configuration for the MCP Benchmarking Client."""

    model_config = ConfigDict(extra="forbid")

    transport: Literal["stdio", "sse", "streamable_http"] = Field(
        default="stdio",
        description="Transport mechanism to use when attaching to the target MCP server",
    )
    stdio: StdioConnectionConfig | None = Field(default=None)
    http: HttpConnectionConfig | None = Field(default=None)
    default_tool_timeout_seconds: float = Field(default=15.0, gt=0)
    sparql_tool_timeout_seconds: float = Field(default=30.0, gt=0)

    @classmethod
    def from_eval_config(
        cls,
        config_path: str | Path = "benchmarking/config/eval_config.yaml",
        transport_override: Literal["stdio", "sse", "streamable_http"] | None = None,
    ) -> MCPConnectionConfig:
        """Load connection and timeout settings directly from eval_config.yaml."""
        path = Path(config_path)
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        timeouts = raw.get("timeouts", {})
        mcp_target = raw.get("mcp_target", {})
        transport = transport_override or mcp_target.get("default_transport", "stdio")

        stdio_cfg = None
        if "stdio" in mcp_target:
            stdio_cfg = StdioConnectionConfig(**mcp_target["stdio"])

        http_cfg = None
        if transport == "sse" and "sse" in mcp_target:
            http_cfg = HttpConnectionConfig(
                url=mcp_target["sse"]["url"],
                headers=mcp_target["sse"].get("headers"),
                connect_timeout_seconds=timeouts.get("mcp_connect_timeout_seconds", 10.0),
                sse_read_timeout_seconds=timeouts.get("mcp_sse_read_timeout_seconds", 300.0),
            )
        elif transport == "streamable_http" and "streamable_http" in mcp_target:
            http_cfg = HttpConnectionConfig(
                url=mcp_target["streamable_http"]["url"],
                headers=mcp_target["streamable_http"].get("headers"),
                connect_timeout_seconds=timeouts.get("mcp_connect_timeout_seconds", 10.0),
                sse_read_timeout_seconds=timeouts.get("mcp_sse_read_timeout_seconds", 300.0),
            )

        return cls(
            transport=transport,
            stdio=stdio_cfg,
            http=http_cfg,
            default_tool_timeout_seconds=timeouts.get("mcp_tool_call_timeout_seconds", 15.0),
            sparql_tool_timeout_seconds=timeouts.get("sparql_query_timeout_seconds", 30.0),
        )


class ExpectedToolSchema(BaseModel):
    """Pydantic model for a single tool entry inside tools_schema.json."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    required_core: bool = True
    inputSchema: dict[str, Any]


class ToolsSchemaSpec(BaseModel):
    """Pydantic model representing the full tools_schema.json specification."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.0.0"
    core_required_tools: list[str] = Field(default_factory=list)
    tools: list[ExpectedToolSchema] = Field(default_factory=list)

    @classmethod
    def from_json_file(cls, path: str | Path = "benchmarking/config/tools_schema.json") -> ToolsSchemaSpec:
        """Load and validate tools_schema.json."""
        file_path = Path(path)
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def to_openai_tools(self, only_core: bool = False) -> list[dict[str, Any]]:
        """Convert the expected MCP tool definitions into OpenAI/LiteLLM function tool format."""
        result: list[dict[str, Any]] = []
        for tool in self.tools:
            if only_core and not tool.required_core:
                continue
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                }
            )
        return result


class ParameterMismatch(BaseModel):
    """Details a parameter-level schema discrepancy for a matched tool name."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    missing_expected_properties: list[str] = Field(default_factory=list)
    unexpected_server_properties: list[str] = Field(default_factory=list)
    type_mismatches: dict[str, dict[str, Any]] = Field(default_factory=dict)
    required_fields_mismatch: dict[str, list[str]] = Field(default_factory=dict)


class ToolSchemaIntrospectionReport(BaseModel):
    """Structured report comparing the target server's list_tools() output with tools_schema.json."""

    model_config = ConfigDict(extra="forbid")

    server_exposed_tools: list[str] = Field(default_factory=list)
    expected_core_tools: list[str] = Field(default_factory=list)
    expected_all_tools: list[str] = Field(default_factory=list)
    matched_core_tools: list[str] = Field(default_factory=list)
    missing_core_tools: list[str] = Field(default_factory=list)
    missing_extended_tools: list[str] = Field(default_factory=list)
    unexpected_extra_tools: list[str] = Field(default_factory=list)
    parameter_mismatches: list[ParameterMismatch] = Field(default_factory=list)
    is_core_compliant: bool = Field(
        default=False,
        description="True if all 5 core required tools are exposed without missing expected properties",
    )


class MCPToolExecutionResult(BaseModel):
    """Strict Pydantic result returned when executing a tool call or resource read on the MCP server."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any]
    success: bool
    is_error: bool = False
    latency_ms: float
    raw_text_outputs: list[str] = Field(default_factory=list)
    parsed_json_output: Any | None = None
    error_message: str | None = None
    timed_out: bool = False


class MCPBenchmarkClient:
    """Async MCP Client connector for benchmarking an external MCP server over Stdio, SSE, or HTTP."""

    def __init__(self, config: MCPConnectionConfig) -> None:
        self.config = config
        self._exit_stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._discovered_tools: list[types.Tool] = []

    @property
    def session(self) -> ClientSession:
        """Return the active MCP ClientSession or raise RuntimeError if not connected."""
        if self._session is None:
            raise RuntimeError("MCPBenchmarkClient is not connected. Use `async with client:` or `await client.connect()`.")
        return self._session

    async def connect(self) -> None:
        """Establish transport connection and initialize the MCP ClientSession."""
        if self._session is not None:
            return

        self._exit_stack = AsyncExitStack()
        try:
            if self.config.transport == "stdio":
                if self.config.stdio is None:
                    raise ValueError("Stdio transport selected, but `config.stdio` is None.")
                server_params = StdioServerParameters(
                    command=self.config.stdio.command,
                    args=self.config.stdio.args,
                    env=self.config.stdio.env,
                    cwd=self.config.stdio.cwd,
                )
                read_stream, write_stream = await self._exit_stack.enter_async_context(
                    stdio_client(server_params)
                )

            elif self.config.transport == "sse":
                if self.config.http is None:
                    raise ValueError("SSE transport selected, but `config.http` is None.")
                read_stream, write_stream = await self._exit_stack.enter_async_context(
                    sse_client(
                        url=self.config.http.url,
                        headers=self.config.http.headers,
                        timeout=self.config.http.connect_timeout_seconds,
                        sse_read_timeout=self.config.http.sse_read_timeout_seconds,
                    )
                )

            elif self.config.transport == "streamable_http":
                if self.config.http is None:
                    raise ValueError("Streamable HTTP transport selected, but `config.http` is None.")
                streams = await self._exit_stack.enter_async_context(
                    streamable_http_client(url=self.config.http.url)
                )
                if isinstance(streams, tuple):
                    read_stream, write_stream = streams[0], streams[1]
                else:
                    read_stream = getattr(streams, "read_stream", streams[0])
                    write_stream = getattr(streams, "write_stream", streams[1])
            else:
                raise ValueError(f"Unsupported MCP transport: {self.config.transport}")

            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        """Close the active MCP session and underlying transport cleanly."""
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            finally:
                self._exit_stack = None
                self._session = None

    async def __aenter__(self) -> MCPBenchmarkClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def list_tools(self) -> list[types.Tool]:
        """Fetch the list of tools exposed by the connected MCP server."""
        result = await self.session.list_tools()
        self._discovered_tools = list(result.tools)
        return self._discovered_tools

    async def get_openai_tools_from_server(self) -> list[dict[str, Any]]:
        """Dynamically convert the server's live `list_tools()` response into OpenAI/LiteLLM tool definitions."""
        tools = await self.list_tools()
        openai_tools: list[dict[str, Any]] = []
        for t in tools:
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema if isinstance(t.inputSchema, dict) else {"type": "object", "properties": {}},
                    },
                }
            )
        return openai_tools

    @staticmethod
    def validate_tools_against_schema(
        server_tools: list[types.Tool] | list[dict[str, Any]],
        expected_spec: ToolsSchemaSpec,
    ) -> ToolSchemaIntrospectionReport:
        """Compare live tools returned by `list_tools()` against `tools_schema.json`."""
        def cls_allowed_types(prop_schema: dict[str, Any]) -> set[str]:
            if "type" in prop_schema and isinstance(prop_schema["type"], str):
                return {prop_schema["type"]}
            if "anyOf" in prop_schema and isinstance(prop_schema["anyOf"], list):
                return {item["type"] for item in prop_schema["anyOf"] if isinstance(item, dict) and "type" in item}
            return set()

        normalized_server: dict[str, dict[str, Any]] = {}
        for item in server_tools:
            if isinstance(item, dict):
                name = item["name"]
                schema = item.get("inputSchema", {})
            else:
                name = item.name
                schema = item.inputSchema if isinstance(item.inputSchema, dict) else {}
            normalized_server[name] = schema

        server_names = sorted(normalized_server.keys())
        core_expected = list(expected_spec.core_required_tools)
        all_expected = [t.name for t in expected_spec.tools]
        expected_by_name = {t.name: t for t in expected_spec.tools}

        matched_core = [name for name in core_expected if name in normalized_server]
        missing_core = [name for name in core_expected if name not in normalized_server]
        missing_extended = [
            name for name in all_expected if name not in core_expected and name not in normalized_server
        ]
        unexpected_extra = [name for name in server_names if name not in expected_by_name]

        param_mismatches: list[ParameterMismatch] = []
        for name, exp_tool in expected_by_name.items():
            if name not in normalized_server:
                continue
            srv_schema = normalized_server[name]
            exp_schema = exp_tool.inputSchema

            exp_props: dict[str, Any] = exp_schema.get("properties", {})
            srv_props: dict[str, Any] = srv_schema.get("properties", {})

            missing_props = sorted(set(exp_props.keys()) - set(srv_props.keys()))
            extra_props = sorted(set(srv_props.keys()) - set(exp_props.keys()))

            type_mismatches: dict[str, dict[str, Any]] = {}
            for prop_name in sorted(set(exp_props.keys()) & set(srv_props.keys())):
                exp_prop = exp_props[prop_name]
                srv_prop = srv_props[prop_name]
                exp_allowed = cls_allowed_types(exp_prop)
                srv_allowed = cls_allowed_types(srv_prop)
                if exp_allowed and srv_allowed and not (exp_allowed & srv_allowed):
                    type_mismatches[prop_name] = {
                        "expected": sorted(exp_allowed),
                        "actual": sorted(srv_allowed),
                    }

            exp_req = sorted(exp_schema.get("required", []))
            srv_req = sorted(srv_schema.get("required", []))
            req_mismatch: dict[str, list[str]] = {}
            if exp_req != srv_req:
                req_mismatch = {"expected": exp_req, "actual": srv_req}

            if missing_props or extra_props or type_mismatches or req_mismatch:
                param_mismatches.append(
                    ParameterMismatch(
                        tool_name=name,
                        missing_expected_properties=missing_props,
                        unexpected_server_properties=extra_props,
                        type_mismatches=type_mismatches,
                        required_fields_mismatch=req_mismatch,
                    )
                )

        core_param_issues = any(
            m.tool_name in core_expected and bool(m.missing_expected_properties or m.type_mismatches)
            for m in param_mismatches
        )
        is_core_compliant = len(missing_core) == 0 and not core_param_issues

        return ToolSchemaIntrospectionReport(
            server_exposed_tools=server_names,
            expected_core_tools=core_expected,
            expected_all_tools=all_expected,
            matched_core_tools=matched_core,
            missing_core_tools=missing_core,
            missing_extended_tools=missing_extended,
            unexpected_extra_tools=unexpected_extra,
            parameter_mismatches=param_mismatches,
            is_core_compliant=is_core_compliant,
        )

    async def introspect_and_validate(
        self,
        schema_path: str | Path = "benchmarking/config/tools_schema.json",
    ) -> ToolSchemaIntrospectionReport:
        """Call `list_tools()` on the connected MCP server and validate against `tools_schema.json`."""
        expected_spec = ToolsSchemaSpec.from_json_file(schema_path)
        live_tools = await self.list_tools()
        return self.validate_tools_against_schema(live_tools, expected_spec)

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> MCPToolExecutionResult:
        """Invoke a tool (or `read_resource` pseudo-tool) on the target MCP server with timeout enforcement."""
        args = arguments or {}
        if timeout_seconds is None:
            if tool_name == "sparql_query":
                timeout_seconds = self.config.sparql_tool_timeout_seconds
            else:
                timeout_seconds = self.config.default_tool_timeout_seconds

        start_perf = time.perf_counter()
        try:
            if tool_name == "read_resource" and "uri" in args:
                res = await asyncio.wait_for(
                    self.session.read_resource(args["uri"]),
                    timeout=timeout_seconds,
                )
                latency_ms = (time.perf_counter() - start_perf) * 1000.0
                raw_texts: list[str] = []
                for content_item in res.contents:
                    text_val = getattr(content_item, "text", None)
                    if text_val is not None:
                        raw_texts.append(text_val)
                parsed_json = self._try_parse_json(raw_texts)
                return MCPToolExecutionResult(
                    tool_name=tool_name,
                    arguments=args,
                    success=True,
                    is_error=False,
                    latency_ms=latency_ms,
                    raw_text_outputs=raw_texts,
                    parsed_json_output=parsed_json,
                )

            call_res = await asyncio.wait_for(
                self.session.call_tool(tool_name, arguments=args),
                timeout=timeout_seconds,
            )
            latency_ms = (time.perf_counter() - start_perf) * 1000.0

            raw_texts = []
            for block in getattr(call_res, "content", []):
                text_val = getattr(block, "text", None)
                if text_val is not None:
                    raw_texts.append(text_val)

            is_err = bool(getattr(call_res, "isError", False))
            parsed_json = self._try_parse_json(raw_texts)

            return MCPToolExecutionResult(
                tool_name=tool_name,
                arguments=args,
                success=not is_err,
                is_error=is_err,
                latency_ms=latency_ms,
                raw_text_outputs=raw_texts,
                parsed_json_output=parsed_json,
                error_message="\n".join(raw_texts) if is_err else None,
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_perf) * 1000.0
            return MCPToolExecutionResult(
                tool_name=tool_name,
                arguments=args,
                success=False,
                is_error=True,
                latency_ms=latency_ms,
                error_message=f"Tool '{tool_name}' timed out after {timeout_seconds:.1f}s",
                timed_out=True,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_perf) * 1000.0
            return MCPToolExecutionResult(
                tool_name=tool_name,
                arguments=args,
                success=False,
                is_error=True,
                latency_ms=latency_ms,
                error_message=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _try_parse_json(raw_texts: list[str]) -> Any | None:
        """Attempt to parse the first or combined text output as JSON."""
        if not raw_texts:
            return None
        if len(raw_texts) == 1:
            try:
                return json.loads(raw_texts[0])
            except Exception:
                return None
        parsed_items: list[Any] = []
        for txt in raw_texts:
            try:
                parsed_items.append(json.loads(txt))
            except Exception:
                return None
        return parsed_items
