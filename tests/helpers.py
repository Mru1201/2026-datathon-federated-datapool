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
    from src.legacy.data_repository import DataRepository

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


_MCP_RESULTS: dict = {}


def mcp_call_once(name: str, arguments: dict | None = None) -> tuple[bool, str]:
    """mcp_call, but each (tool, arguments) runs only once per test session.

    The tools are read-only queries against the live endpoint; several tests check the
    same call's output, so they share one result instead of re-sending heavy queries.
    """
    import server

    # The protocol layer swaps in an offline client; keep its results apart from live ones.
    key = (server.sparql.endpoint, name, json.dumps(arguments or {}, sort_keys=True))
    if key not in _MCP_RESULTS:
        _MCP_RESULTS[key] = mcp_call(name, arguments)
    return _MCP_RESULTS[key]


class CachingSparqlClient:
    """SparqlClient for tests: each (query, params) is sent once per test session."""

    def __new__(cls, *args, **kwargs):
        from src.sparql_client import SparqlClient

        class _Caching(SparqlClient):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.cache = {}

            def query(self, sparql: str) -> dict:
                if sparql not in self.cache:
                    self.cache[sparql] = super().query(sparql)
                return self.cache[sparql]

        return _Caching(*args, **kwargs)


def pretty(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:300]


# ---- SPARQL parity: directory.ttl is the single source --------------------------

TTL_FILE = DATA_DIR.parent / "directory.ttl"

TTL_PREFIXES = """\
@prefix schema: <http://schema.org/> .
@prefix org: <http://www.w3.org/ns/org#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix cdf: <https://civic-data.de/federated-directory#> .
"""


def load_graph(turtle: str | None = None):
    """The RDF source: directory.ttl, or a small Turtle snippet for edge cases."""
    import rdflib

    graph = rdflib.Graph()
    if turtle is None:
        graph.parse(TTL_FILE)
    else:
        graph.parse(data=TTL_PREFIXES + turtle, format="turtle")
    return graph


def graph_to_frames(graph) -> dict:
    """Tables for the old CSV code, derived from the RDF graph.

    One row per entity of each dataset class (DATASETS in src/sparql_client.py), one
    column per CSV column, value = the property's value as text, NaN when absent.
    A property with several values cannot be one CSV cell, so it raises.
    """
    import rdflib

    from src.sparql_client import DATASETS, expand

    frames = {}
    for name, dataset in DATASETS.items():
        records = []
        rdf_class = rdflib.URIRef(expand(dataset["class"]))
        for subject in sorted(set(graph.subjects(rdflib.RDF.type, rdf_class)), key=str):
            record = {"iri": str(subject)}
            for column in dataset["columns"][1:]:
                values = list(graph.objects(subject, rdflib.URIRef(expand(column))))
                if len(values) > 1:
                    raise ValueError(f"{subject} has {len(values)} values for {column}")
                record[column] = str(values[0]) if values else float("nan")
            records.append(record)
        frames[name] = pd.DataFrame(records, columns=dataset["columns"], dtype=object)
    return frames


class LocalSparqlClient:
    """SparqlClient that runs queries on an in-memory rdflib graph instead of HTTP."""

    def __new__(cls, graph):
        from src.sparql_client import SparqlClient

        class _Local(SparqlClient):
            def query(self, sparql: str) -> dict:
                result = json.loads(graph.query(sparql).serialize(format="json"))
                if "results" in result:
                    # rdflib quirk: GROUP BY over zero matches yields one empty row;
                    # the SPARQL spec (and the live Fuseki endpoint) yield none.
                    result["results"]["bindings"] = [
                        b for b in result["results"]["bindings"] if b
                    ]
                return result

        return _Local(endpoint="local://rdflib")


def make_sources(turtle: str | None = None):
    """(DataRepository, LocalSparqlClient) over the same RDF data.

    The client runs the real .rq files on the graph; the old CSV code gets the tables
    derived from the same graph (graph_to_frames).
    """
    from src.legacy.data_repository import DataRepository

    graph = load_graph(turtle)
    return DataRepository(graph_to_frames(graph)), LocalSparqlClient(graph)


def normalize(value):
    """NaN -> None recursively, so pandas output compares with SPARQL output."""
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, float) and value != value:
        return None
    return value
