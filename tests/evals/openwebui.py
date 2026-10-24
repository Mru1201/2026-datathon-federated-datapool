"""Open WebUI backend for the tool-calling evals.

Flow per case: send prompt + the real server's tool schemas to the model, execute
any tool calls on the real MCP server, feed results back, score the outcome.
Every failure is classified by a `stage` so the report says exactly where it broke.
"""

import json
import os
import time
from dataclasses import dataclass, field

import httpx

from tests.helpers import mcp_call, mcp_list_tools

SYSTEM_PROMPT = (
    "You are an assistant for AWO (Arbeiterwohlfahrt) facility and service data. "
    "Use the provided tools to answer questions; do not guess facts you can look up."
)
MAX_STEPS = 5

# Stages, in the order a run can fail
STAGE_REQUEST = "model request failed"
STAGE_NO_TOOL = "model did not call a tool"
STAGE_UNKNOWN_TOOL = "model called a tool that does not exist"
STAGE_WRONG_TOOL = "wrong tool chosen"
STAGE_BAD_ARGS = "wrong tool arguments"
STAGE_TOOL_ERROR = "tool execution returned an error"
STAGE_NO_FINAL = "model gave no final answer"
STAGE_ANSWER = "final answer missing expected content"


def base_url() -> str:
    return os.environ.get("OPENWEBUI_URL", "http://localhost:3000").rstrip("/")


def make_client() -> httpx.Client:
    key = os.environ.get("OPENWEBUI_API_KEY")
    if not key:
        raise RuntimeError("OPENWEBUI_API_KEY not set (see .env.example)")
    return httpx.Client(
        base_url=base_url(), headers={"Authorization": f"Bearer {key}"}, timeout=300
    )


def list_models() -> list[str]:
    with make_client() as c:
        r = c.get("/api/models")
        r.raise_for_status()
        return [m["id"] for m in r.json()["data"]]


def openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema,
            },
        }
        for t in mcp_list_tools()
    ]


@dataclass
class RunResult:
    model: str
    case_id: str
    run: int
    passed: bool
    stage: str = ""
    detail: str = ""
    seconds: float = 0.0
    calls: list = field(default_factory=list)  # [(tool, args)]
    answer: str = ""

    def describe(self) -> str:
        calls = "; ".join(f"{n}({json.dumps(a, ensure_ascii=False)})" for n, a in self.calls) or "none"
        return (
            f"run {self.run}: FAILED at stage '{self.stage}'\n"
            f"      {self.detail}\n"
            f"      tool calls: {calls}\n"
            f"      final answer: {self.answer[:200]!r}"
        )


def _args_mismatch(expected: dict, actual: dict) -> str:
    """Expected string args must appear (case-insensitive substring) in the actual ones."""
    problems = []
    for key, want in expected.items():
        got = actual.get(key)
        if got is None:
            problems.append(f"missing argument '{key}' (expected ~{want!r})")
        elif str(want).casefold() not in str(got).casefold():
            problems.append(f"argument '{key}'={got!r}, expected it to contain {want!r}")
    return "; ".join(problems)


def run_case(client: httpx.Client, model: str, case: dict, run: int, tools: list[dict]) -> RunResult:
    start = time.monotonic()
    result = RunResult(model=model, case_id=case["id"], run=run, passed=False)
    known = {t["function"]["name"] for t in tools}
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": case["prompt"]},
    ]

    def fail(stage: str, detail: str) -> RunResult:
        result.stage, result.detail = stage, detail
        result.seconds = round(time.monotonic() - start, 1)
        return result

    for _ in range(MAX_STEPS):
        try:
            response = client.post(
                "/api/chat/completions",
                json={"model": model, "messages": messages, "tools": tools,
                      "stream": False, "temperature": 0},
            )
        except httpx.HTTPError as exc:
            return fail(STAGE_REQUEST, f"{type(exc).__name__}: {exc}")
        if response.status_code != 200:
            return fail(STAGE_REQUEST, f"HTTP {response.status_code}: {response.text[:300]}")
        try:
            message = response.json()["choices"][0]["message"]
        except (KeyError, IndexError, ValueError):
            return fail(STAGE_REQUEST, f"unexpected response body: {response.text[:300]}")

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            result.answer = message.get("content") or ""
            if not result.calls:
                return fail(STAGE_NO_TOOL, "the model answered directly instead of using a tool")
            if not result.answer.strip():
                return fail(STAGE_NO_FINAL, "after the tool result the model returned an empty reply")
            missing = [s for s in case.get("answer_contains", []) if s.casefold() not in result.answer.casefold()]
            if missing:
                return fail(STAGE_ANSWER, f"final answer does not contain {missing}")
            result.passed = True
            result.seconds = round(time.monotonic() - start, 1)
            return result

        messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
        for call in tool_calls:
            name = call["function"]["name"]
            raw_args = call["function"].get("arguments") or {}
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {}
                result.calls.append((name, raw_args))
                return fail(STAGE_BAD_ARGS, f"arguments are not valid JSON: {raw_args!r}")
            result.calls.append((name, args))

            if name not in known:
                return fail(STAGE_UNKNOWN_TOOL, f"'{name}' is not one of {sorted(known)}")
            if len(result.calls) == 1:  # score the first tool choice
                if name != case["expect_tool"]:
                    return fail(STAGE_WRONG_TOOL, f"expected '{case['expect_tool']}', model chose '{name}'")
                mismatch = _args_mismatch(case.get("expect_args", {}), args)
                if mismatch:
                    return fail(STAGE_BAD_ARGS, mismatch)
            is_error, text = mcp_call(name, args)
            if is_error:
                return fail(STAGE_TOOL_ERROR, f"{name}({args}) -> {text[:300]}")
            messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": text})

    return fail(STAGE_NO_FINAL, f"no final answer after {MAX_STEPS} tool-calling steps")
