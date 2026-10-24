"""Helpers shared by the test layers."""

import asyncio
import csv
import json
from pathlib import Path

import pandas as pd

from conftest import DATA_DIR

CSV_FILES = {
    "einrichtung": "einrichtungSchema.csv",
    "adresse": "adresseSchema.csv",
    "angebot": "angebotSchema.csv",
    "traeger": "traegerSchema.csv",
}


def raw_rows(dataset: str) -> list[dict]:
    """Read a dataset with the csv module (independent of pandas/DataLoader)."""
    with open(DATA_DIR / CSV_FILES[dataset], newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def make_repo(einrichtung=(), adresse=(), angebot=(), traeger=()):
    """Build a DataRepository from small synthetic rows.

    Rows are dicts; columns not given are NaN. Column names come from the real CSVs.
    """
    from src.data_repository import DataRepository

    given = {
        "einrichtung": einrichtung,
        "adresse": adresse,
        "angebot": angebot,
        "traeger": traeger,
    }
    frames = {}
    for name, rows in given.items():
        with open(DATA_DIR / CSV_FILES[name], newline="", encoding="utf-8") as f:
            columns = next(csv.reader(f))
        frames[name] = pd.DataFrame(list(rows), columns=columns)
    return DataRepository(frames)


# ---- MCP in-memory client (sync wrappers) --------------------------------

def _server():
    import server

    return server.mcp


def mcp_list_tools():
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    async def run():
        async with connect(_server()._mcp_server) as client:
            return (await client.list_tools()).tools

    return asyncio.run(run())


def mcp_call(name: str, arguments: dict | None = None) -> tuple[bool, str]:
    """Call a tool on the real server in-process. Returns (is_error, text)."""
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    async def run():
        async with connect(_server()._mcp_server) as client:
            result = await client.call_tool(name, arguments or {})
            text = "".join(
                part.text for part in result.content if getattr(part, "text", None)
            )
            return result.isError, text

    return asyncio.run(run())


def pretty(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:300]
