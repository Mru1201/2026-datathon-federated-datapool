"""SPARQL tools vs. the old CSV logic: do the new queries do exactly the same thing?

Offline, no network. The source is RDF: data/directory.ttl (or a small Turtle snippet for edge
cases), loaded into an in-memory rdflib graph. Both implementations get the same data:

* new: the real .rq files in sparql_queries/ run on the graph (LocalSparqlClient)
* old: DataRepository runs on tables derived from the graph (graph_to_frames), one row
  per entity and one column per CSV column, exactly the shape it read from the CSVs

The old result is the expected value.
"""

import csv

import pytest

from conftest import DATA_DIR
from src.sparql_client import (
    DATASETS, column_variable, escape_literal, expand, load_query, rows, to_float,
)
from tests.helpers import (
    CSV_FILES, LocalSparqlClient, graph_to_frames, load_graph, make_sources, normalize,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

CDF = "https://civic-data.de/federated-directory#"
CITIES = ["Berlin", "berlin", "BERLIN", "Atlantis"]
NAMES = ["Drehscheibe", "drehscheibe", "Lübecker", "(HLS6)", ".*", "AWO", ""]
SERVICE_QUERIES = ["Suchtberatung", "sucht", "Senioren", "Pflege", "Beratung", "xyz-nothing", ""]


@pytest.fixture(scope="module")
def sources():
    return make_sources()


def by_iri(items):
    return sorted(items, key=lambda item: item["iri"])


def coordinates_as_float(details):
    """The old code returned coordinates as read from the CSV; the new one as floats."""
    for detail in details:
        address = detail.get("address")
        if address:
            for key in ("latitude", "longitude"):
                address[key] = to_float(address[key])
    return details


def expected_duplicates(frames):
    """The old detect_duplicates logic (pandas), but with the IRI column left out."""
    result = {}
    for name, df in frames.items():
        data = df.drop(columns="iri")
        dup = df[data.duplicated(keep=False)]
        if dup.empty:
            continue
        groups = []
        for _, group in dup.groupby(list(data.columns), dropna=False, sort=False):
            groups.append({
                "occurrences": len(group),
                "iris": sorted(group["iri"]),
                "row": normalize(group.drop(columns="iri").iloc[0].to_dict()),
            })
        result[name] = sorted(groups, key=lambda g: g["iris"])
    return result


def sorted_duplicates(result):
    return {
        name: sorted(
            [{**g, "iris": sorted(g["iris"])} for g in groups], key=lambda g: g["iris"]
        )
        for name, groups in result.items()
    }


# ---- helpers in src/sparql_client.py -------------------------------------------

def test_rows_flattens_bindings_and_maps_empty_to_none():
    result = {
        "head": {"vars": ["a", "b", "c"]},
        "results": {"bindings": [{"a": {"type": "literal", "value": "x"},
                                  "b": {"type": "literal", "value": ""}}]},
    }
    assert rows(result) == [{"a": "x", "b": None, "c": None}]


def test_expand_and_column_variable():
    assert expand("schema:postalCode") == "http://schema.org/postalCode"
    assert expand("cdf:parentOrgClassification") == CDF + "parentOrgClassification"
    assert column_variable("schema:postalCode") == "postal_code"
    assert column_variable("cdf:parentOrgClassification") == "parent_org_classification"


def test_to_float():
    assert to_float("52.5") == 52.5
    assert to_float(None) is None


@pytest.mark.parametrize("dataset", list(DATASETS))
def test_dataset_columns_match_csv_headers(dataset):
    with open(DATA_DIR / CSV_FILES[dataset], newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert DATASETS[dataset]["columns"] == header, (
        f"DATASETS['{dataset}']['columns'] in src/sparql_client.py differs from the CSV header"
    )


@pytest.mark.parametrize("dataset", list(DATASETS))
def test_duplicate_query_selects_every_column(dataset):
    query = load_query(DATASETS[dataset]["duplicates_query"])
    for column in DATASETS[dataset]["columns"][1:]:
        assert f"?entity {column} ?{column_variable(column)}_" in query, (
            f"{DATASETS[dataset]['duplicates_query']}.rq does not compare column {column}"
        )


# ---- parity on directory.ttl -------------------------------------------------------

@pytest.mark.parametrize("city", CITIES)
def test_count_facilities_parity(sources, city):
    repo, client = sources
    assert client.count_facilities(city) == repo.count_facilities(city)


@pytest.mark.parametrize("city", CITIES)
def test_search_facilities_parity(sources, city):
    repo, client = sources
    assert client.search_facilities(city) == by_iri(normalize(repo.search_facilities(city)))


@pytest.mark.parametrize("name", NAMES)
def test_get_facility_details_parity(sources, name):
    repo, client = sources
    expected = coordinates_as_float(by_iri(normalize(repo.get_facility_details(name))))
    assert client.get_facility_details(name) == expected


@pytest.mark.parametrize("query", SERVICE_QUERIES)
def test_search_services_parity(sources, query):
    repo, client = sources
    assert client.search_services(query) == by_iri(normalize(repo.search_services(query)))


def test_detect_duplicates_parity(sources):
    _, client = sources
    expected = expected_duplicates(graph_to_frames(load_graph()))
    assert sorted_duplicates(client.detect_duplicates()) == expected


def test_check_completeness_parity(sources):
    repo, client = sources
    assert client.check_completeness() == normalize(repo.check_completeness())


@pytest.mark.parametrize("section", [
    "dataset_sizes", "facilities_by_city", "facilities_by_category",
    "facilities_by_provider", "facility_relationships",
    "services_by_category", "services_by_audience",
])
def test_generate_statistics_parity(sources, section):
    repo, client = sources
    assert client.generate_statistics()[section] == normalize(repo.generate_statistics())[section]


def test_compare_facilities_parity(sources):
    repo, client = sources
    expected = [
        {"search_name": side["search_name"],
         "matches": coordinates_as_float(by_iri(normalize(side["matches"])))}
        for side in repo.compare_facilities("Drehscheibe", "Metropolitankapitel")
    ]
    assert client.compare_facilities("Drehscheibe", "Metropolitankapitel") == expected


# ---- edge cases (small Turtle snippets, both implementations) ----------------------

def test_casefold_matches_eszett_like_python():
    repo, client = make_sources("""
        cdf:org-a a org:OrganizationalUnit ; schema:name "A" ; schema:address cdf:addr-1 .
        cdf:addr-1 a schema:PostalAddress ; schema:addressLocality "Gießen" .
    """)
    for city in ("Gießen", "GIESSEN", "giessen"):
        assert client.count_facilities(city) == repo.count_facilities(city) == 1


def test_dangling_address_is_skipped_like_csv():
    repo, client = make_sources("""
        cdf:org-a a org:OrganizationalUnit ; schema:name "A" ; schema:address cdf:addr-missing .
    """)
    assert client.count_facilities("Berlin") == repo.count_facilities("Berlin") == 0
    assert client.search_facilities("Berlin") == repo.search_facilities("Berlin") == []
    assert "address" not in client.get_facility_details("A")[0]
    assert client.generate_statistics()["facility_relationships"]["without_address"] == 1


def test_whitespace_values_count_as_missing_and_are_trimmed():
    repo, client = make_sources("""
        cdf:org-a a org:OrganizationalUnit ; schema:name "   " ; schema:category " Pflege " .
        cdf:org-b a org:OrganizationalUnit ; schema:name "B" ; schema:category "Pflege" .
    """)
    assert client.check_completeness() == normalize(repo.check_completeness())
    assert client.check_completeness()["einrichtung"]["columns_detail"]["schema:name"]["missing"] == 1
    stats = client.generate_statistics()
    assert stats["facilities_by_category"] == {"Pflege": 2}
    assert stats == normalize(repo.generate_statistics())


def test_injected_duplicate_is_found():
    _, client = make_sources("""
        cdf:org-a a org:OrganizationalUnit ; schema:name "Twin" ; schema:telephone "030 1" .
        cdf:org-b a org:OrganizationalUnit ; schema:name "Twin" ; schema:telephone "030 1" .
        cdf:org-c a org:OrganizationalUnit ; schema:name "Other" .
    """)
    duplicates = client.detect_duplicates()
    assert list(duplicates) == ["einrichtung"]
    [group] = duplicates["einrichtung"]
    assert group["occurrences"] == 2
    assert sorted(group["iris"]) == [f"{CDF}org-a", f"{CDF}org-b"]
    assert group["row"]["schema:name"] == "Twin" and group["row"]["schema:email"] is None


def test_quote_in_input_stays_inside_the_literal():
    _, client = make_sources("""
        cdf:org-a a org:OrganizationalUnit ; schema:name "Haus \\"Kelebek\\"" .
    """)
    assert client.get_facility_details('"Kelebek"')[0]["name"] == 'Haus "Kelebek"'
    assert client.get_facility_details('x") || true || ("') == []
    assert client.search_services('x") || true || ("') == []


def test_empty_city_matches_nothing():
    """A facility without an address is in no city, so an empty city matches nothing."""
    repo, client = make_sources("""
        cdf:org-a a org:OrganizationalUnit ; schema:name "No address" .
    """)
    assert client.count_facilities("") == repo.count_facilities("") == 0
    assert client.search_facilities("") == repo.search_facilities("") == []


def test_multi_valued_contacts_are_joined():
    """RDF allows several emails per facility (a CSV cell cannot); all are kept, joined by '; '."""
    graph = load_graph("""
        cdf:org-a a org:OrganizationalUnit ; schema:name "A" ; schema:address cdf:addr-1 ;
            schema:email "a@x.de", "b@x.de" .
        cdf:addr-1 a schema:PostalAddress ; schema:addressLocality "Berlin" .
    """)
    client = LocalSparqlClient(graph)
    [result] = client.search_facilities("Berlin")
    assert sorted(result["email"].split("; ")) == ["a@x.de", "b@x.de"]
    assert client.count_facilities("Berlin") == 1
    with pytest.raises(ValueError, match="2 values"):
        graph_to_frames(graph)


def test_escape_literal_used_for_every_placeholder():
    query = load_query("list_services_by_query", query='a"b')
    assert escape_literal('a"b') in query and 'a"b"' not in query
