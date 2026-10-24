"""Run the MCP protocol tests offline: the server's SPARQL client reads directory.ttl."""

import pytest

from tests.helpers import LocalSparqlClient, load_graph


@pytest.fixture(scope="package", autouse=True)
def offline_server():
    import server

    live = server.sparql
    server.sparql = LocalSparqlClient(load_graph())
    yield
    server.sparql = live
