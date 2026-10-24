"""LLM tool-calling evals through Open WebUI.

One test per (model, case). Cases live in cases.json: add an entry for every new
tool/feature. Run: pytest -m llm tests/evals --models a,b --runs 3
"""

import json
from pathlib import Path

import pytest

from tests.evals import openwebui
from tests.evals.conftest import RESULTS

pytestmark = pytest.mark.llm

CASES = json.loads((Path(__file__).parent / "cases.json").read_text())


@pytest.fixture(scope="module")
def client():
    try:
        c = openwebui.make_client()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    yield c
    c.close()


@pytest.fixture(scope="module")
def tools():
    return openwebui.openai_tools()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_tool_calling(request, client, tools, model, case):
    runs = request.config.getoption("--runs")
    threshold = request.config.getoption("--pass-threshold")

    results = [openwebui.run_case(client, model, case, i + 1, tools) for i in range(runs)]
    RESULTS.extend(results)

    passed = sum(r.passed for r in results)
    if passed / runs < threshold:
        failed = "\n    ".join(r.describe() for r in results if not r.passed)
        pytest.fail(
            f"model '{model}' on case '{case['id']}' passed {passed}/{runs} "
            f"(need >= {threshold:.0%}).\n"
            f"  prompt: {case['prompt']!r}\n"
            f"  expected: tool '{case['expect_tool']}' with {case.get('expect_args', {})}\n"
            f"  failures:\n    {failed}",
            pytrace=False,
        )
