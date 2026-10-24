"""SPARQL API layer: do the tools work against the live endpoint?

Integration tests: real .rq files, real SparqlClient, real endpoint, and the real MCP
server (in-memory client). Logical equivalence with the old CSV code is checked offline
in tests/unit/test_sparql_parity.py; here we check consistency on the live data.

Needs network access to the SPARQL endpoint ($SPARQL_ENDPOINT or the CorrelAid
default). Tests that need it are skipped when the endpoint is unreachable.
Expected values come from a differently shaped query counted in Python, not from
the code under test.
"""

import json
import re

import pytest

from src.sparql_client import QUERY_DIR, SparqlClient, escape_literal, load_query
from tests.helpers import CachingSparqlClient, mcp_call_once

pytestmark = pytest.mark.api


@pytest.fixture(scope="module")
def client():
    client = CachingSparqlClient()
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
    assert '= "Ber\\"lin")' in query, f"city not escaped in query:\n{query}"


def test_load_query_without_required_param_raises():
    with pytest.raises(ValueError, match="city"):
        load_query("count_facilities_by_city")


@pytest.mark.parametrize("path", sorted(QUERY_DIR.glob("*.rq")), ids=lambda p: p.name)
def test_query_files_follow_naming_convention(path):
    match = re.fullmatch(
        r"(count|list|get|ask)_([a-z]+(?:_[a-z]+)*?)(?:_by_([a-z_]+?))?(?:_per_([a-z_]+))?\.rq",
        path.name,
    )
    assert match, f"{path.name} does not follow <action>_<entity>[_by_<param>][_per_<group>].rq (QUERIES.md)"
    text = path.read_text(encoding="utf-8")
    assert "# Params:" in text and "# Used by:" in text, (
        f"{path.name} is missing its '# Params:' / '# Used by:' header comment"
    )
    params = set(re.findall(r"\{\{(\w+)\}\}", text))
    by = match.group(3) or ""
    for param in params:
        assert by.startswith(param), f"{path.name} takes {{{{{param}}}}} but its name has no _by_{param}"
    if not params:
        assert not by, f"{path.name} is named _by_{by} but takes no parameter"
    if match.group(4):
        assert "GROUP BY" in text, f"{path.name} is named _per_{match.group(4)} but has no GROUP BY"


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


def test_mcp_count_facilities_returns_reference_count(client):
    is_error, text = mcp_call_once("count_facilities", {"city": "Berlin"})
    assert not is_error, f"count_facilities returned an MCP error: {text[:300]}"
    expected = expected_city_count(client, "Berlin")
    assert text.strip() == str(expected), (
        f"count_facilities('Berlin') returned {text!r}, expected {expected}"
    )


# ---- live: every tool ----------------------------------------------------------

CITY_KEYS = {"iri", "name", "street", "postal_code", "city", "telephone", "email", "homepage"}
DETAIL_KEYS = {
    "iri", "name", "alternate_name", "telephone", "email", "homepage",
    "category", "service_description",
}
SERVICE_KEYS = {"iri", "schema:name", "schema:category", "schema:audience"}
DATASET_NAMES = {"einrichtung", "adresse", "angebot", "traeger"}


@pytest.fixture(scope="module")
def statistics(client):
    return client.generate_statistics()


@pytest.fixture(scope="module")
def completeness(client):
    return client.check_completeness()


def test_search_facilities_matches_count_and_reference(client):
    results = client.search_facilities("Berlin")
    assert len(results) == client.count_facilities("Berlin")
    reference = {
        r["facility"]["value"]
        for r in client.query(load_query("list_facility_cities_by_city_substring", city="berlin"))["results"]["bindings"]
        if r["city"]["value"].casefold() == "berlin"
    }
    assert {r["iri"] for r in results} == reference


def test_search_facilities_result_shape_and_city(client):
    results = client.search_facilities("berlin")
    assert results
    for facility in results:
        assert set(facility) == CITY_KEYS, f"unexpected keys {sorted(facility)}"
        assert facility["city"].casefold() == "berlin", f"{facility['iri']} is in {facility['city']!r}"


def test_get_facility_details_known_facility(client):
    results = client.get_facility_details("drehscheibe")
    assert results, "no facility named like 'Drehscheibe' on the endpoint"
    for detail in results:
        assert DETAIL_KEYS <= set(detail) <= DETAIL_KEYS | {"address", "provider"}
        assert "drehscheibe" in detail["name"].casefold()
    known = {d["iri"]: d for d in results}.get(
        "https://civic-data.de/federated-directory#org-00416a783a9b"
    )
    assert known is not None, "facility org-00416a783a9b (Drehscheibe) not returned"
    assert known["address"]["city"] == "Berlin"
    assert known["provider"]["name"].startswith("SPI")


def test_get_facility_details_unknown_name_is_empty(client):
    assert client.get_facility_details("Atlantis-Gibtsnicht-XYZ") == []


def test_search_services_every_result_matches(client):
    results = client.search_services("Suchtberatung")
    assert results
    assert len({r["iri"] for r in results}) == len(results), "a service is listed twice"
    for service in results:
        assert set(service) == SERVICE_KEYS
        fields = [service["schema:name"], service["schema:category"], service["schema:audience"]]
        assert any("suchtberatung" in (f or "").casefold() for f in fields), service


def test_detect_duplicates_structure(client):
    duplicates = client.detect_duplicates()
    assert set(duplicates) <= DATASET_NAMES
    for dataset, groups in duplicates.items():
        for group in groups:
            assert group["occurrences"] == len(group["iris"]) >= 2, (dataset, group)
            assert "iri" not in group["row"]


def test_check_completeness_consistent(client, completeness, statistics):
    assert set(completeness) == DATASET_NAMES
    for dataset, info in completeness.items():
        assert info["rows"] == statistics["dataset_sizes"][dataset]
        assert info["columns_detail"]["iri"]["missing"] == 0
        assert info["missing_cells"] == sum(c["missing"] for c in info["columns_detail"].values())
        assert info["total_cells"] == info["rows"] * info["columns"]
        for column, detail in info["columns_detail"].items():
            assert 0 <= detail["missing"] <= detail["total"], (dataset, column, detail)
            assert 0 <= detail["missing_percentage"] <= 100, (dataset, column, detail)


def test_generate_statistics_consistent(client, statistics):
    sizes = statistics["dataset_sizes"]
    assert set(sizes) == DATASET_NAMES and all(n > 0 for n in sizes.values()), sizes
    links = statistics["facility_relationships"]
    assert links["with_address"] + links["without_address"] == sizes["einrichtung"]
    assert links["with_provider"] + links["without_provider"] == sizes["einrichtung"]
    assert statistics["facilities_by_city"]["Berlin"] == client.count_facilities("Berlin")
    assert sum(statistics["facilities_by_provider"].values()) >= links["with_provider"]
    assert sum(statistics["services_by_category"].values()) <= sizes["angebot"]


def test_compare_facilities_equals_two_detail_lookups(client):
    result = client.compare_facilities("Drehscheibe", "Metropolitankapitel")
    assert [side["search_name"] for side in result] == ["Drehscheibe", "Metropolitankapitel"]
    assert result[0]["matches"] == client.get_facility_details("Drehscheibe")
    assert result[1]["matches"] == client.get_facility_details("Metropolitankapitel")
    assert all(side["matches"] for side in result)


# ---- live: MCP server returns exactly what the client returns ----------------------

MCP_CASES = {
    "count_facilities": ({"city": "Berlin"}, "count_facilities", ("Berlin",)),
    "search_facilities": ({"city": "Berlin"}, "search_facilities", ("Berlin",)),
    "get_facility_details": ({"name": "Drehscheibe"}, "get_facility_details", ("Drehscheibe",)),
    "search_services": ({"query": "Suchtberatung"}, "search_services", ("Suchtberatung",)),
    "detect_duplicates": ({}, "detect_duplicates", ()),
    "check_completeness": ({}, "check_completeness", ()),
    "generate_statistics": ({}, "generate_statistics", ()),
    "compare_facilities": (
        {"facility_1": "Drehscheibe", "facility_2": "Metropolitankapitel"},
        "compare_facilities", ("Drehscheibe", "Metropolitankapitel"),
    ),
}


@pytest.mark.parametrize("tool", sorted(MCP_CASES))
def test_mcp_tool_returns_client_result(client, tool):
    arguments, method, args = MCP_CASES[tool]
    is_error, text = mcp_call_once(tool, arguments)
    assert not is_error, f"{tool}({arguments}) returned an MCP error: {text[:300]}"
    assert json.loads(text) == getattr(client, method)(*args), (
        f"{tool}({arguments}) over MCP differs from SparqlClient.{method}{args}"
    )
