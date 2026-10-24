import httpx


SPARQL_JSON_ACCEPT = "application/sparql-results+json"


class SparqlClient:
    """Thin synchronous wrapper around a SPARQL 1.1 HTTP endpoint."""

    def __init__(self, client: httpx.Client, endpoint: str) -> None:
        self._client = client
        self._endpoint = endpoint

    def query(self, sparql: str) -> dict:
        """POST a SPARQL SELECT/ASK query and return the parsed JSON response."""
        response = self._client.post(
            self._endpoint,
            data={"query": sparql},
            headers={"Accept": SPARQL_JSON_ACCEPT},
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def bindings(result: dict) -> list[dict]:
        """Extract the bindings list from a SPARQL JSON result."""
        return result.get("results", {}).get("bindings", [])

    @staticmethod
    def value(binding: dict, var: str) -> str | None:
        """Safely extract a literal or URI value from one binding row."""
        cell = binding.get(var)
        return cell["value"] if cell else None
