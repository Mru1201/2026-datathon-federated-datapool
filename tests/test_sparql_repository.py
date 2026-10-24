import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.sparql_client import SparqlClient
from src.sparql_repository import SparqlRepository

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _make_repo(fixture_name: str) -> SparqlRepository:
    """Return a SparqlRepository whose client returns the given fixture."""
    mock_client = MagicMock(spec=SparqlClient)
    mock_client.query.return_value = _load_fixture(fixture_name)
    mock_client.bindings.side_effect = SparqlClient.bindings
    mock_client.value.side_effect = SparqlClient.value
    return SparqlRepository(mock_client, cache_ttl=0)


class TestCountFacilities:
    def test_returns_integer(self):
        repo = _make_repo("count_facilities")
        result = repo.count_facilities("Berlin")
        assert result == 42

    def test_empty_bindings_returns_zero(self):
        mock_client = MagicMock(spec=SparqlClient)
        mock_client.query.return_value = {"results": {"bindings": []}}
        mock_client.bindings.side_effect = SparqlClient.bindings
        mock_client.value.side_effect = SparqlClient.value
        repo = SparqlRepository(mock_client, cache_ttl=0)
        assert repo.count_facilities("Nowhere") == 0


class TestSearchFacilities:
    def test_returns_list_of_dicts(self):
        repo = _make_repo("search_facilities")
        results = repo.search_facilities("Berlin")
        assert isinstance(results, list)
        assert len(results) == 1

    def test_result_has_expected_keys(self):
        repo = _make_repo("search_facilities")
        item = repo.search_facilities("Berlin")[0]
        assert "name" in item
        assert "city" in item
        assert "iri" in item

    def test_city_value_correct(self):
        repo = _make_repo("search_facilities")
        item = repo.search_facilities("Berlin")[0]
        assert item["city"] == "Berlin"


class TestGetFacilityDetails:
    def test_returns_list(self):
        repo = _make_repo("get_facility_details")
        results = repo.get_facility_details("AWO")
        assert isinstance(results, list)
        assert len(results) == 1

    def test_result_has_address_block(self):
        repo = _make_repo("get_facility_details")
        item = repo.get_facility_details("AWO")[0]
        assert "address" in item
        assert item["address"]["city"] == "Berlin"

    def test_result_has_provider_block(self):
        repo = _make_repo("get_facility_details")
        item = repo.get_facility_details("AWO")[0]
        assert "provider" in item
        assert item["provider"]["name"] == "AWO Berlin"


class TestCompareFacilities:
    def test_returns_two_entries(self):
        mock_client = MagicMock(spec=SparqlClient)
        mock_client.query.return_value = _load_fixture("get_facility_details")
        mock_client.bindings.side_effect = SparqlClient.bindings
        mock_client.value.side_effect = SparqlClient.value
        repo = SparqlRepository(mock_client, cache_ttl=0)
        result = repo.compare_facilities("AWO Mitte", "AWO Wedding")
        assert len(result) == 2
        assert result[0]["search_name"] == "AWO Mitte"
        assert result[1]["search_name"] == "AWO Wedding"
