"""DataLoader: do the four CSVs load completely and consistently?"""

import pytest

from src.legacy.data_loader import DataLoader
from tests.helpers import CSV_FILES, raw_rows

REQUIRED_COLUMNS = {
    "einrichtung": [
        "iri", "schema:name", "schema:alternateName", "schema:telephone",
        "schema:email", "foaf:homepage", "schema:category",
        "schema:availableService", "schema:parentOrganization", "schema:address",
    ],
    "adresse": [
        "iri", "schema:streetAddress", "schema:postalCode",
        "schema:addressLocality", "schema:addressCountry",
        "schema:latitude", "schema:longitude",
    ],
    "angebot": ["iri", "schema:name", "schema:category", "schema:audience"],
    "traeger": ["iri", "schema:name", "foaf:homepage", "schema:address"],
}


def test_load_all_returns_four_datasets(datasets):
    assert set(datasets) == set(CSV_FILES), (
        f"DataLoader.load_all() returned keys {sorted(datasets)}, "
        f"expected {sorted(CSV_FILES)} (src/legacy/data_loader.py: load_all)"
    )


@pytest.mark.parametrize("name", list(CSV_FILES))
def test_row_count_matches_csv(datasets, name):
    expected = len(raw_rows(name))
    actual = len(datasets[name])
    assert actual == expected, (
        f"dataset '{name}': loaded {actual} rows but data/{CSV_FILES[name]} "
        f"has {expected} (rows lost or added while loading)"
    )


@pytest.mark.parametrize("name", list(CSV_FILES))
def test_required_columns_present(datasets, name):
    missing = [c for c in REQUIRED_COLUMNS[name] if c not in datasets[name].columns]
    assert not missing, (
        f"dataset '{name}' is missing column(s) {missing} that "
        f"src/legacy/data_repository.py reads; CSV columns: {list(datasets[name].columns)}"
    )


@pytest.mark.parametrize("name", list(CSV_FILES))
def test_iri_is_unique_and_filled(datasets, name):
    iris = datasets[name]["iri"]
    assert not iris.isna().any(), (
        f"dataset '{name}': {int(iris.isna().sum())} row(s) have an empty iri"
    )
    dupes = iris[iris.duplicated()].tolist()
    assert not dupes, f"dataset '{name}': duplicate iri values, e.g. {dupes[:3]}"


def test_umlauts_survive_loading(datasets):
    names = " ".join(datasets["einrichtung"]["schema:name"].dropna())
    assert "Lübecker" in names, (
        "expected the facility name containing 'Lübecker' in einrichtung; "
        "umlauts are probably being mangled (encoding problem in src/legacy/data_loader.py)"
    )


def test_missing_directory_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError) as excinfo:
        DataLoader(tmp_path / "nope").load_all()
    assert "einrichtungSchema.csv" in str(excinfo.value) or "angebotSchema.csv" in str(
        excinfo.value
    ), f"FileNotFoundError should name the missing CSV, got: {excinfo.value}"


def test_facility_address_references_resolve(datasets):
    """Every address IRI used by a facility must exist in the address dataset."""
    known = set(datasets["adresse"]["iri"])
    used = datasets["einrichtung"]["schema:address"].dropna()
    dangling = used[~used.isin(known)].tolist()
    assert not dangling, (
        f"{len(dangling)} facility address IRI(s) not found in adresse, "
        f"e.g. {dangling[:3]}"
    )


def test_facility_provider_references_resolve(datasets):
    """Every parentOrganization IRI used by a facility must exist in traeger."""
    known = set(datasets["traeger"]["iri"])
    used = datasets["einrichtung"]["schema:parentOrganization"].dropna()
    dangling = used[~used.isin(known)].tolist()
    assert not dangling, (
        f"{len(dangling)} facility provider IRI(s) not found in traeger, "
        f"e.g. {dangling[:3]}"
    )
