import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_ENDPOINT = "https://sosuse.correlaid.org/directory/sparql"

QUERY_DIR = Path(__file__).resolve().parent.parent / "sparql_queries"

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def escape_literal(value: str) -> str:
    """Escape a Python string for use inside a double-quoted SPARQL literal."""

    replacements = {
        "\\": "\\\\",
        '"': '\\"',
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
    }

    return "".join(replacements.get(char, char) for char in value)


def load_query(name: str, **params: str) -> str:
    """
    Load sparql_queries/<name>.rq and fill its {{placeholders}}.

    Values are escaped as SPARQL string literals.
    """

    template = (QUERY_DIR / f"{name}.rq").read_text(encoding="utf-8")

    missing = sorted(set(PLACEHOLDER.findall(template)) - set(params))
    if missing:
        raise ValueError(f"query '{name}' needs parameter(s) {missing}")

    return PLACEHOLDER.sub(
        lambda match: escape_literal(str(params[match.group(1)])),
        template,
    )


class SparqlClient:
    """Query the federated directory of social support services over SPARQL."""

    def __init__(self, endpoint: str | None = None, timeout: float = 30):
        self.endpoint = endpoint or os.environ.get(
            "SPARQL_ENDPOINT", DEFAULT_ENDPOINT
        )
        self.timeout = timeout

    def query(self, sparql: str) -> dict:
        """Run a SPARQL query and return the parsed JSON result."""

        url = self.endpoint + "?" + urllib.parse.urlencode({"query": sparql})
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/sparql-results+json"},
        )

        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def count_facilities(self, city: str) -> int:
        """Count facilities in a city."""

        result = self.query(load_query("count_facilities_by_city", city=city))
        bindings = result["results"]["bindings"]

        return int(bindings[0]["count"]["value"]) if bindings else 0
