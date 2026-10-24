import threading
import time

from src.sparql_client import SparqlClient
from src.query_loader import build


class SparqlRepository:
    """
    Query layer for the federated welfare directory SPARQL endpoint.

    All methods load their SPARQL from files in queries/ and return plain
    Python dicts/lists so the server layer can serialise them to JSON.
    """

    def __init__(self, client: SparqlClient, cache_ttl: int = 300) -> None:
        self._client = client
        self._cache_ttl = cache_ttl
        self._stats_cache: dict | None = None
        self._stats_cache_time: float = 0.0
        self._stats_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Facility queries
    # ------------------------------------------------------------------

    def count_facilities(self, city: str) -> int:
        result = self._client.query(build("count_facilities", city=city))
        bindings = SparqlClient.bindings(result)
        if not bindings:
            return 0
        raw = SparqlClient.value(bindings[0], "count")
        return int(raw) if raw is not None else 0

    def search_facilities(self, city: str) -> list[dict]:
        result = self._client.query(build("search_facilities", city=city))
        return [_map_facility(b) for b in SparqlClient.bindings(result)]

    def get_facility_details(self, name: str) -> list[dict]:
        result = self._client.query(build("get_facility_details", name=name))
        return [_map_facility_detail(b) for b in SparqlClient.bindings(result)]

    def compare_facilities(self, name1: str, name2: str) -> list[dict]:
        return [
            {"search_name": name1, "matches": self.get_facility_details(name1)},
            {"search_name": name2, "matches": self.get_facility_details(name2)},
        ]

    def search_by_postal_code(self, postal_code: str) -> list[dict]:
        result = self._client.query(
            build("search_by_postal_code", postal_code=postal_code)
        )
        return [_map_facility(b) for b in SparqlClient.bindings(result)]

    # ------------------------------------------------------------------
    # Service queries
    # ------------------------------------------------------------------

    def search_services(self, query: str) -> list[dict]:
        result = self._client.query(build("search_services", query=query))
        return [_map_service(b) for b in SparqlClient.bindings(result)]

    # ------------------------------------------------------------------
    # Provider queries
    # ------------------------------------------------------------------

    def list_providers(self) -> list[dict]:
        result = self._client.query(build("list_providers"))
        return [_map_provider(b) for b in SparqlClient.bindings(result)]

    # ------------------------------------------------------------------
    # Statistics (cached)
    # ------------------------------------------------------------------

    def generate_statistics(self) -> dict:
        with self._stats_lock:
            now = time.monotonic()
            if (
                self._stats_cache is not None
                and self._cache_ttl > 0
                and (now - self._stats_cache_time) < self._cache_ttl
            ):
                return self._stats_cache

            stats = self._compute_statistics()
            self._stats_cache = stats
            self._stats_cache_time = now
            return stats

    def _compute_statistics(self) -> dict:
        by_city = self._client.query(build("statistics_by_city"))
        by_category = self._client.query(build("statistics_by_category"))
        by_provider = self._client.query(build("statistics_by_provider"))

        return {
            "facilities_by_city": [
                {
                    "city": SparqlClient.value(b, "city"),
                    "count": int(SparqlClient.value(b, "count") or 0),
                }
                for b in SparqlClient.bindings(by_city)
            ],
            "facilities_by_category": [
                {
                    "category": SparqlClient.value(b, "category"),
                    "count": int(SparqlClient.value(b, "count") or 0),
                }
                for b in SparqlClient.bindings(by_category)
            ],
            "facilities_by_provider": [
                {
                    "provider": SparqlClient.value(b, "providerName"),
                    "count": int(SparqlClient.value(b, "count") or 0),
                }
                for b in SparqlClient.bindings(by_provider)
            ],
        }


# ------------------------------------------------------------------
# Private mapping helpers
# ------------------------------------------------------------------

def _map_facility(b: dict) -> dict:
    v = SparqlClient.value
    return {
        "iri": v(b, "facility"),
        "name": v(b, "name"),
        "street": v(b, "street"),
        "postal_code": v(b, "postalCode"),
        "city": v(b, "city"),
        "telephone": v(b, "telephone"),
        "email": v(b, "email"),
        "homepage": v(b, "homepage"),
    }


def _map_facility_detail(b: dict) -> dict:
    v = SparqlClient.value
    return {
        "iri": v(b, "facility"),
        "name": v(b, "name"),
        "alternate_name": v(b, "alternateName"),
        "telephone": v(b, "telephone"),
        "email": v(b, "email"),
        "homepage": v(b, "homepage"),
        "category": v(b, "category"),
        "address": {
            "street": v(b, "street"),
            "postal_code": v(b, "postalCode"),
            "city": v(b, "city"),
            "country": v(b, "country"),
            "latitude": v(b, "lat"),
            "longitude": v(b, "lon"),
        },
        "provider": {
            "iri": v(b, "providerIri"),
            "name": v(b, "providerName"),
            "homepage": v(b, "providerHomepage"),
        },
    }


def _map_service(b: dict) -> dict:
    v = SparqlClient.value
    return {
        "iri": v(b, "service"),
        "name": v(b, "name"),
        "category": v(b, "category"),
        "audience": v(b, "audience"),
    }


def _map_provider(b: dict) -> dict:
    v = SparqlClient.value
    return {
        "iri": v(b, "provider"),
        "name": v(b, "name"),
        "homepage": v(b, "homepage"),
        "address": {
            "street": v(b, "street"),
            "postal_code": v(b, "postalCode"),
            "city": v(b, "city"),
        },
    }
