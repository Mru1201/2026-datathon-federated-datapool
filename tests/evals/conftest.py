"""Eval plumbing: pick models, collect results, print + write the report."""

import json
import os
from pathlib import Path

import pytest

from conftest import ROOT

RESULTS: list = []  # RunResult objects, appended by test_tool_calling.py


def resolve_models(config) -> list[str]:
    from tests.evals import openwebui

    wanted = [m.strip() for m in config.getoption("--models").split(",") if m.strip()]
    if wanted == ["all"]:
        return openwebui.list_models()
    if wanted:
        return wanted
    pinned = os.environ.get("OPENWEBUI_MODEL")
    return [pinned] if pinned else openwebui.list_models()[:1]


def pytest_generate_tests(metafunc):
    if "model" not in metafunc.fixturenames:
        return
    try:
        models = resolve_models(metafunc.config)
    except Exception as exc:  # noqa: BLE001
        models = []
        reason = f"cannot list models from Open WebUI ({exc!r}); check .env"
    if not models:
        metafunc.parametrize(
            "model",
            [pytest.param(None, marks=pytest.mark.skip(reason=locals().get("reason", "no models")))],
        )
    else:
        metafunc.parametrize("model", models)


def _matrix(results) -> tuple[list[str], list[str], dict]:
    models = sorted({r.model for r in results})
    cases = list(dict.fromkeys(r.case_id for r in results))
    cell = {}
    for r in results:
        passed, total = cell.get((r.model, r.case_id), (0, 0))
        cell[(r.model, r.case_id)] = (passed + r.passed, total + 1)
    return models, cases, cell


def _markdown(results) -> str:
    models, cases, cell = _matrix(results)
    lines = ["## Tool-calling eval results", "",
             "| case | " + " | ".join(models) + " |",
             "|---|" + "---|" * len(models)]
    for case in cases:
        row = []
        for m in models:
            p, t = cell.get((m, case), (0, 0))
            row.append(("✅" if p == t else "⚠️" if p else "❌") + f" {p}/{t}")
        lines.append(f"| {case} | " + " | ".join(row) + " |")
    failures = [r for r in results if not r.passed]
    if failures:
        lines += ["", "### Failures", ""]
        for r in failures:
            lines.append(f"- **{r.model} / {r.case_id}** (run {r.run}): {r.stage} — {r.detail}")
    return "\n".join(lines) + "\n"


def pytest_terminal_summary(terminalreporter):
    if not RESULTS:
        return
    markdown = _markdown(RESULTS)
    terminalreporter.write_sep("=", "tool-calling eval report")
    terminalreporter.write(markdown)

    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "eval-report.md").write_text(markdown)
    (out / "eval-report.json").write_text(
        json.dumps([r.__dict__ for r in RESULTS], indent=2, ensure_ascii=False, default=str)
    )
    terminalreporter.write_line(f"report written to {out}/eval-report.md and .json")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(markdown)
