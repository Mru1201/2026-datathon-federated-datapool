"""SPARQL API layer: does count_facilities_with_api agree with the live endpoint?

Needs network access to the SPARQL endpoint ($SPARQL_ENDPOINT or the CorrelAid
default). Tests that need it are skipped when the endpoint is unreachable.
Expected values come from a differently shaped query counted in Python, not from
the code under test.
"""

import re

import pytest

from src.sparql_client import QUERY_DIR, SparqlClient, escape_literal, load_query
from tests.helpers import mcp_call

pytestmark = pytest.mark.api


@pytest.fixture(scope="module")
def client():
    client = SparqlClient()
    try:
        assert client.query("ASK {}")["boolean"] is True
    except Exception as exc:  # noqa: BLE001 - any failure means "unreachable"
        pytest.skip(f"SPARQL endpoint {client.endpoint} unreachable: {exc!r}")
    return client


def expected_city_count(client: SparqlClient, city: str) -> int:
    """Fetch facility/locality pairs broadly, then match the city in Python."""
    query = load_query("list_facility_cities_by_city_substring", city=city)
    rows = client.query(query)["results"]["bindings"]
    return len({
        r["facility"]["value"]
        for r in rows
        if r["city"]["value"].casefold() == city.casefold()
    })


# ---- offline: query building -------------------------------------------------

def test_escape_literal_escapes_quotes_and_backslashes():
    assert escape_literal('a"b\\c\nd') == 'a\\"b\\\\c\\nd'


def test_load_query_embeds_escaped_city():
    query = load_query("count_facilities_by_city", city='Ber"lin')
    assert 'LCASE("Ber\\"lin")' in query, f"city not escaped in query:\n{query}"


def test_load_query_without_required_param_raises():
    with pytest.raises(ValueError, match="city"):
        load_query("count_facilities_by_city")


@pytest.mark.parametrize("path", sorted(QUERY_DIR.glob("*.rq")), ids=lambda p: p.name)
def test_query_files_follow_naming_convention(path):
    assert re.fullmatch(r"(count|list|get|ask)_[a-z]+(_[a-z]+)*_by_[a-z_]+\.rq", path.name), (
        f"{path.name} does not follow <action>_<entity>_by_<filter>.rq (QUERIES.md)"
    )
    header = path.read_text(encoding="utf-8")
    assert "# Params:" in header and "# Used by:" in header, (
        f"{path.name} is missing its '# Params:' / '# Used by:' header comment"
    )


# ---- live endpoint -----------------------------------------------------------

@pytest.mark.parametrize("city", ["Berlin", "München", "Köln"])
def test_count_matches_independent_query(client, city):
    expected = expected_city_count(client, city)
    actual = client.count_facilities(city)
    assert expected > 0, f"sanity: no facilities found for {city} on {client.endpoint}"
    assert actual == expected, (
        f"count_facilities({city!r}) returned {actual}, expected {expected}"
    )


def test_city_match_is_case_insensitive(client):
    counts = {c: client.count_facilities(c) for c in ("Berlin", "berlin", "BERLIN")}
    assert len(set(counts.values())) == 1, f"case changes the count: {counts}"


def test_unknown_city_returns_zero(client):
    assert client.count_facilities("Atlantis-Gibtsnicht") == 0


def test_query_injection_does_not_widen_match(client):
    city = 'x") || true || ("'
    assert client.count_facilities(city) == 0, (
        "a quote in the city name changed the FILTER: escaping in load_query failed"
    )


def test_mcp_tool_returns_api_count(client):
    is_error, text = mcp_call("count_facilities_with_api", {"city": "Berlin"})
    assert not is_error, f"count_facilities_with_api returned an MCP error: {text[:300]}"
    expected = expected_city_count(client, "Berlin")
    assert text.strip() == str(expected), (
        f"count_facilities_with_api('Berlin') returned {text!r}, expected {expected}"
    )
