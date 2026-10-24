"""DataRepository: business logic behind every MCP tool.

Expected values are derived from the raw CSVs (csv module), not from the code
under test. Edge cases use small synthetic datasets (tests.helpers.make_repo).
"""

import pytest

from tests.helpers import make_repo, raw_rows

CITY_KEYS = {"iri", "name", "street", "postal_code", "city", "telephone", "email", "homepage"}
DETAIL_KEYS = {
    "iri", "name", "alternate_name", "telephone", "email", "homepage",
    "category", "service_description",
}


def expected_city_count(city: str) -> int:
    locality = {a["iri"]: a["schema:addressLocality"] for a in raw_rows("adresse")}
    return sum(
        1
        for e in raw_rows("einrichtung")
        if locality.get(e["schema:address"], "").casefold() == city.casefold()
    )


def expected_service_matches(query: str) -> int:
    q = query.casefold()
    return sum(
        1
        for s in raw_rows("angebot")
        if any(q in s[c].casefold() for c in ("schema:name", "schema:category", "schema:audience"))
    )


# ---- count_facilities / search_facilities ---------------------------------

@pytest.mark.parametrize("city", ["Berlin", "berlin", "BERLIN"])
def test_count_facilities_is_case_insensitive(repository, city):
    expected = expected_city_count("Berlin")
    actual = repository.count_facilities(city)
    assert expected > 0, "test data sanity: no facilities in Berlin in the CSVs"
    assert actual == expected, (
        f"count_facilities({city!r}) returned {actual}, expected {expected} "
        "(counted independently from adresse/einrichtung CSVs)"
    )


def test_count_facilities_unknown_city_is_zero(repository):
    actual = repository.count_facilities("Atlantis")
    assert actual == 0, f"count_facilities('Atlantis') returned {actual}, expected 0"


def test_count_facilities_empty_string_is_zero(repository):
    actual = repository.count_facilities("")
    assert actual == 0, (
        f"count_facilities('') returned {actual}; an empty city should match nothing "
        "but it matches facilities that have no address"
    )


def test_count_equals_search_length(repository):
    count = repository.count_facilities("Berlin")
    found = len(repository.search_facilities("Berlin"))
    assert count == found, (
        f"count_facilities('Berlin')={count} but len(search_facilities('Berlin'))={found}; "
        "the two methods disagree on what 'in Berlin' means"
    )


def test_search_facilities_result_shape_and_city(repository):
    results = repository.search_facilities("Berlin")
    assert results, "search_facilities('Berlin') returned nothing"
    for i, facility in enumerate(results):
        assert set(facility) == CITY_KEYS, (
            f"search_facilities result #{i} has keys {sorted(facility)}, "
            f"expected {sorted(CITY_KEYS)}"
        )
        assert facility["city"].casefold() == "berlin", (
            f"search_facilities('Berlin') result #{i} ({facility['name']!r}) "
            f"has city {facility['city']!r}"
        )


def test_search_facilities_skips_facilities_without_address():
    repo = make_repo(
        einrichtung=[
            {"iri": "e1", "schema:name": "Has address", "schema:address": "a1"},
            {"iri": "e2", "schema:name": "No address", "schema:address": None},
            {"iri": "e3", "schema:name": "Dangling", "schema:address": "missing"},
        ],
        adresse=[{"iri": "a1", "schema:addressLocality": "Berlin"}],
    )
    names = [f["name"] for f in repo.search_facilities("Berlin")]
    assert names == ["Has address"], (
        f"search_facilities with missing/dangling address returned {names}, "
        "expected only ['Has address']"
    )


# ---- get_facility_details -------------------------------------------------

def test_get_facility_details_partial_case_insensitive(repository):
    results = repository.get_facility_details("drehscheibe kinder")
    assert len(results) == 1, (
        f"get_facility_details('drehscheibe kinder') returned {len(results)} "
        "match(es), expected 1"
    )
    assert "Drehscheibe" in results[0]["name"], f"unexpected facility: {results[0]['name']!r}"


def test_get_facility_details_shape_and_address(repository):
    result = repository.get_facility_details("Drehscheibe")[0]
    missing = DETAIL_KEYS - set(result)
    assert not missing, f"facility details missing key(s): {sorted(missing)}"
    assert "address" in result, "facility has an address in the data but 'address' is missing"
    assert result["address"]["city"], "address.city is empty for 'Drehscheibe'"


def test_get_facility_details_unknown_name_is_empty(repository):
    results = repository.get_facility_details("zzz-no-such-facility")
    assert results == [], f"expected [], got {len(results)} result(s)"


def test_get_facility_details_treats_query_literally(repository):
    """Regex characters must not be interpreted (regex=False)."""
    assert repository.get_facility_details(".*") == [], (
        "get_facility_details('.*') matched facilities: the query is being used as a regex"
    )
    parens = repository.get_facility_details("(HLS6)")
    assert len(parens) == 1, (
        f"get_facility_details('(HLS6)') returned {len(parens)} match(es), expected 1"
    )


def test_get_facility_details_includes_provider_when_linked():
    repo = make_repo(
        einrichtung=[
            {"iri": "e1", "schema:name": "Kita A", "schema:parentOrganization": "t1"}
        ],
        traeger=[{"iri": "t1", "schema:name": "AWO Test e.V."}],
    )
    result = repo.get_facility_details("Kita")[0]
    assert result.get("provider", {}).get("name") == "AWO Test e.V.", (
        f"provider not attached to facility, got: {result.get('provider')}"
    )


# ---- search_services ------------------------------------------------------

@pytest.mark.parametrize("query", ["Suchtberatung", "suchtberatung", "Sucht", "Senioren"])
def test_search_services_count_matches_csv(repository, query):
    expected = expected_service_matches(query)
    actual = len(repository.search_services(query))
    assert actual == expected, (
        f"search_services({query!r}) returned {actual} result(s), expected {expected} "
        "(name/category/audience substring match counted from angebotSchema.csv)"
    )


def test_search_services_result_shape(repository):
    results = repository.search_services("Suchtberatung")
    expected_keys = {"iri", "schema:name", "schema:category", "schema:audience"}
    assert results, "search_services('Suchtberatung') returned nothing"
    assert set(results[0]) == expected_keys, (
        f"service result keys {sorted(results[0])}, expected {sorted(expected_keys)}"
    )


def test_search_services_no_match_is_empty(repository):
    assert repository.search_services("zzz-no-such-service") == []


# ---- detect_duplicates ----------------------------------------------------

def test_detect_duplicates_clean_data_reports_nothing(repository):
    result = repository.detect_duplicates()
    non_empty = {k: len(v) for k, v in result.items() if v}
    assert not non_empty, f"real data has no exact duplicate rows but got groups: {non_empty}"


def test_detect_duplicates_finds_injected_duplicate():
    row = {"iri": "x", "schema:name": "Same"}
    repo = make_repo(angebot=[row, row, {"iri": "y", "schema:name": "Other"}])
    groups = repo.detect_duplicates()["angebot"]
    assert len(groups) == 1, f"expected 1 duplicate group in angebot, got {len(groups)}"
    assert groups[0]["occurrences"] == 2, f"occurrences={groups[0]['occurrences']}, expected 2"
    assert groups[0]["row"]["iri"] == "x"


# ---- check_completeness ---------------------------------------------------

def test_check_completeness_structure_and_ranges(repository, datasets):
    result = repository.check_completeness()
    for name, df in datasets.items():
        info = result[name]
        assert info["rows"] == len(df), f"{name}: rows={info['rows']}, expected {len(df)}"
        assert info["columns"] == len(df.columns), f"{name}: wrong column count"
        assert info["total_cells"] == len(df) * len(df.columns), f"{name}: wrong total_cells"
        assert 0 <= info["missing_percentage"] <= 100, (
            f"{name}: missing_percentage {info['missing_percentage']} outside 0-100"
        )
        assert set(info["columns_detail"]) == set(df.columns), f"{name}: column detail mismatch"


def test_check_completeness_counts_blank_strings_as_missing():
    repo = make_repo(
        traeger=[
            {"iri": "t1", "schema:name": "   "},
            {"iri": "t2", "schema:name": ""},
            {"iri": "t3", "schema:name": None},
            {"iri": "t4", "schema:name": "ok"},
        ]
    )
    detail = repo.check_completeness()["traeger"]["columns_detail"]["schema:name"]
    assert detail["missing"] == 3, (
        f"schema:name missing={detail['missing']}, expected 3 (whitespace, empty and NaN)"
    )
    assert detail["missing_percentage"] == 75.0, f"got {detail['missing_percentage']}"


def test_check_completeness_missing_cells_sum_matches_columns(repository):
    for name, info in repository.check_completeness().items():
        column_sum = sum(c["missing"] for c in info["columns_detail"].values())
        assert info["missing_cells"] == column_sum, (
            f"{name}: missing_cells={info['missing_cells']} but columns add up to {column_sum}"
        )


# ---- generate_statistics --------------------------------------------------

def test_statistics_dataset_sizes(repository):
    sizes = repository.generate_statistics()["dataset_sizes"]
    for name, rows in sizes.items():
        expected = len(raw_rows(name))
        assert rows == expected, f"dataset_sizes[{name}]={rows}, expected {expected}"


def test_statistics_city_counts_agree_with_count_facilities(repository):
    by_city = repository.generate_statistics()["facilities_by_city"]
    assert by_city.get("Berlin") == repository.count_facilities("Berlin"), (
        f"facilities_by_city['Berlin']={by_city.get('Berlin')} but "
        f"count_facilities('Berlin')={repository.count_facilities('Berlin')}"
    )


def test_statistics_relationships_add_up(repository):
    stats = repository.generate_statistics()
    total = stats["dataset_sizes"]["einrichtung"]
    rel = stats["facility_relationships"]
    assert rel["with_address"] + rel["without_address"] == total, (
        f"address relationship counts {rel} do not add up to {total} facilities"
    )
    assert rel["with_provider"] + rel["without_provider"] == total, (
        f"provider relationship counts {rel} do not add up to {total} facilities"
    )


# ---- compare_facilities ---------------------------------------------------

def test_compare_facilities_returns_both_sides(repository):
    result = repository.compare_facilities("Drehscheibe", "Metropolitankapitel")
    assert [r["search_name"] for r in result] == ["Drehscheibe", "Metropolitankapitel"], (
        f"search names not preserved/ordered: {[r['search_name'] for r in result]}"
    )
    for r in result:
        assert r["matches"], f"no match found for {r['search_name']!r}"


def test_compare_facilities_unknown_name_gives_empty_matches(repository):
    result = repository.compare_facilities("Drehscheibe", "zzz-nope")
    assert result[1]["matches"] == [], "unknown facility should yield empty matches"
