"""Shared pytest setup: .env loading, CLI options, common fixtures."""

import os
from pathlib import Path

import pytest

pytest_plugins = ["tests.dashboard.plugin"]

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


def _load_env_file() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_env_file()


def pytest_addoption(parser):
    group = parser.getgroup("llm evals")
    group.addoption(
        "--models",
        default=os.environ.get("EVAL_MODELS", ""),
        help="Comma-separated Open WebUI model ids, or 'all'. "
        "Default: $OPENWEBUI_MODEL or the first listed model.",
    )
    group.addoption(
        "--runs",
        type=int,
        default=int(os.environ.get("EVAL_RUNS", "1")),
        help="Repetitions per (model, case); local models are non-deterministic.",
    )
    group.addoption(
        "--pass-threshold",
        type=float,
        default=float(os.environ.get("EVAL_PASS_THRESHOLD", "1.0")),
        help="Fraction of runs that must pass for a (model, case) to pass.",
    )


def pytest_collection_modifyitems(items):
    """Run fast layers first: unit, protocol, SPARQL API, connection, then the slow LLM evals."""
    order = {"unit": 0, "protocol": 1, "api": 2, "llm": 3, "evals": 4}

    def layer(item):
        parts = Path(str(item.path)).resolve().relative_to(ROOT).parts
        return order.get(parts[1], 9) if len(parts) > 2 else 9

    items.sort(key=layer)  # stable: keeps order within a layer


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA_DIR


@pytest.fixture(scope="session")
def datasets(data_dir):
    from src.legacy.data_loader import DataLoader

    return DataLoader(data_dir).load_all()


@pytest.fixture(scope="session")
def repository(datasets):
    from src.legacy.data_repository import DataRepository

    return DataRepository(datasets)
