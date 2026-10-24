"""Shared pytest setup: .env loading, CLI options, common fixtures."""

import os
from pathlib import Path

import pytest

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


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return DATA_DIR


@pytest.fixture(scope="session")
def datasets(data_dir):
    from src.data_loader import DataLoader

    return DataLoader(data_dir).load_all()


@pytest.fixture(scope="session")
def repository(datasets):
    from src.data_repository import DataRepository

    return DataRepository(datasets)
