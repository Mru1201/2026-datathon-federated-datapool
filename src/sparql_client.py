"""SPARQL client for the federated directory of social support services (SoSuSe).

Every query lives in its own file in sparql_queries/; load_query() fills its {{placeholders}}
and SparqlClient runs it and shapes the rows into the result of one MCP tool. See QUERIES.md.
"""

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_ENDPOINT = "https://sosuse.correlaid.org/directory/sparql"

QUERY_DIR = Path(__file__).resolve().parent.parent / "sparql_queries"

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

NAMESPACES = {
    "schema:": "http://schema.org/",
    "org:": "http://www.w3.org/ns/org#",
    "foaf:": "http://xmlns.com/foaf/0.1/",
    "cdf:": "https://civic-data.de/federated-directory#",
}

# Dataset name -> RDF class, duplicates query and the columns that completeness and
# duplicate checks look at. The column lists are the headers of the original CSV export
# in data/ (kept in sync by tests/unit/test_sparql_parity.py).
DATASETS = {
    "einrichtung": {
        "class": "org:OrganizationalUnit",
        "duplicates_query": "list_duplicate_facilities",
        "columns": [
            "iri", "schema:name", "schema:alternateName", "schema:telephone",
            "schema:email", "foaf:homepage", "schema:mainEntityOfPage",
            "schema:category", "schema:availableService", "schema:audience",
            "schema:accessibilitySummary", "schema:openingHours",
            "schema:parentOrganization", "cdf:parentOrgClassification",
            "schema:address",
        ],
    },
    "adresse": {
        "class": "schema:PostalAddress",
        "duplicates_query": "list_duplicate_addresses",
        "columns": [
            "iri", "schema:streetAddress", "schema:postalCode",
            "schema:addressLocality", "schema:addressCountry",
            "schema:latitude", "schema:longitude",
        ],
    },
    "angebot": {
        "class": "schema:Service",
        "duplicates_query": "list_duplicate_services",
        "columns": [
            "iri", "schema:name", "schema:category", "schema:codeValue",
            "schema:audience", "schema:areaServed", "schema:provider",
        ],
    },
    "traeger": {
        "class": "schema:Organization",
        "duplicates_query": "list_duplicate_providers",
        "columns": ["iri", "schema:name", "foaf:homepage", "schema:address"],
    },
}


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


def expand(prefixed: str) -> str:
    """Expand a prefixed name such as "schema:name" to a full IRI."""

    for prefix, namespace in NAMESPACES.items():
        if prefixed.startswith(prefix):
            return namespace + prefixed[len(prefix):]

    return prefixed


def column_variable(column: str) -> str:
    """Variable name a duplicates query uses for a column ("schema:postalCode" -> "postal_code")."""

    local = column.split(":", 1)[1]

    return re.sub(r"(?<!^)(?=[A-Z])", "_", local).lower()


def rows(result: dict) -> list[dict]:
    """
    Flatten SPARQL JSON bindings to {variable: value} dicts.

    Unbound variables and empty GROUP_CONCAT results become None.
    """

    return [
        {
            variable: (binding[variable]["value"] or None)
            if variable in binding
            else None
            for variable in result["head"]["vars"]
        }
        for binding in result["results"]["bindings"]
    ]


def percentage(part: int, whole: int) -> float:
    """part / whole in percent, rounded to 2 decimals (0.0 when whole is 0)."""

    return round(part / whole * 100, 2) if whole else 0.0


def to_float(value: str | None) -> float | None:
    """Convert a coordinate literal to float (None stays None)."""

    return float(value) if value is not None else None


def load_query(query_name: str, /, **params: str) -> str:
    """
    Load sparql_queries/<query_name>.rq and fill its {{placeholders}}.

    Values are escaped as SPARQL string literals.
    """

    template = (QUERY_DIR / f"{query_name}.rq").read_text(encoding="utf-8")

    missing = sorted(set(PLACEHOLDER.findall(template)) - set(params))
    if missing:
        raise ValueError(f"query '{query_name}' needs parameter(s) {missing}")

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

    def select(self, query_name: str, /, **params: str) -> list[dict]:
        """Run sparql_queries/<query_name>.rq and return its rows."""

        return rows(self.query(load_query(query_name, **params)))

    def value_counts(self, query_name: str) -> dict:
        """Run a count_*_per_* query and return {value: count}."""

        return {
            row["value"]: int(row["count"])
            for row in self.select(query_name)
        }

    def count_facilities(self, city: str) -> int:
        """Count facilities in a city."""

        result = self.select("count_facilities_by_city", city=city.casefold())

        return int(result[0]["count"]) if result else 0

    def search_facilities(self, city: str) -> list[dict]:
        """Find facilities in a city."""

        return [
            {
                "iri": row["facility"],
                "name": row["name"],
                "street": row["street"],
                "postal_code": row["postal_code"],
                "city": row["city"],
                "telephone": row["telephone"],
                "email": row["email"],
                "homepage": row["homepage"],
            }
            for row in self.select("list_facilities_by_city", city=city.casefold())
        ]

    def get_facility_details(self, name: str) -> list[dict]:
        """Find facilities by name and return their details."""

        results = []

        for row in self.select("list_facility_details_by_name", name=name.casefold()):
            result = {
                "iri": row["facility"],
                "name": row["name"],
                "alternate_name": row["alternate_name"],
                "telephone": row["telephone"],
                "email": row["email"],
                "homepage": row["homepage"],
                "category": row["category"],
                "service_description": row["service_description"],
            }

            if row["address"]:
                result["address"] = {
                    "street": row["street"],
                    "postal_code": row["postal_code"],
                    "city": row["city"],
                    "country": row["country"],
                    "latitude": to_float(row["latitude"]),
                    "longitude": to_float(row["longitude"]),
                }

            if row["provider"]:
                result["provider"] = {
                    "iri": row["provider"],
                    "name": row["provider_name"],
                    "homepage": row["provider_homepage"],
                }

            results.append(result)

        return results

    def search_services(self, query: str) -> list[dict]:
        """Search the structured service catalogue."""

        return [
            {
                "iri": row["service"],
                "schema:name": row["name"],
                "schema:category": row["category"],
                "schema:audience": row["audience"],
            }
            for row in self.select("list_services_by_query", query=query.casefold())
        ]

    def detect_duplicates(self) -> dict:
        """
        Detect duplicate entities in all datasets.

        A duplicate group is two or more entities whose values are
        identical in every column except the IRI.
        """

        duplicates = {}

        for dataset_name, dataset in DATASETS.items():
            groups = [
                {
                    "occurrences": int(row["occurrences"]),
                    "iris": row["iris"].split(" "),
                    "row": {
                        column: row[column_variable(column)]
                        for column in dataset["columns"][1:]
                    },
                }
                for row in self.select(dataset["duplicates_query"])
            ]

            if groups:
                duplicates[dataset_name] = groups

        return duplicates

    def dataset_sizes(self) -> dict:
        """Number of entities per dataset."""

        counts = {
            row["class"]: int(row["count"])
            for row in self.select("count_entities_per_class")
        }

        return {
            dataset_name: counts.get(expand(dataset["class"]), 0)
            for dataset_name, dataset in DATASETS.items()
        }

    def check_completeness(self) -> dict:
        """
        Check data completeness for all datasets.

        A value is missing when the property is absent or only whitespace.
        """

        sizes = self.dataset_sizes()

        filled = {
            (row["class"], row["property"]): int(row["filled"])
            for row in self.select("count_filled_properties_per_class")
        }

        completeness = {}

        for dataset_name, dataset in DATASETS.items():
            total_rows = sizes[dataset_name]
            class_iri = expand(dataset["class"])
            columns = {}

            for column in dataset["columns"]:
                if column == "iri":
                    missing = 0
                else:
                    missing = total_rows - filled.get((class_iri, expand(column)), 0)

                columns[column] = {
                    "total": total_rows,
                    "missing": missing,
                    "missing_percentage": percentage(missing, total_rows),
                }

            total_cells = total_rows * len(dataset["columns"])
            total_missing = sum(column["missing"] for column in columns.values())

            completeness[dataset_name] = {
                "rows": total_rows,
                "columns": len(dataset["columns"]),
                "total_cells": total_cells,
                "missing_cells": total_missing,
                "missing_percentage": percentage(total_missing, total_cells),
                "columns_detail": columns,
            }

        return completeness

    def generate_statistics(self) -> dict:
        """Generate statistics for the directory."""

        links = self.select("count_facility_links")[0]
        total = int(links["total"])
        with_address = int(links["with_address"])
        with_provider = int(links["with_provider"])

        return {
            "dataset_sizes": self.dataset_sizes(),
            "facilities_by_city": self.value_counts("count_facilities_per_city"),
            "facilities_by_category": self.value_counts("count_facilities_per_category"),
            "facilities_by_provider": self.value_counts("count_facilities_per_provider"),
            "facility_relationships": {
                "with_address": with_address,
                "without_address": total - with_address,
                "with_provider": with_provider,
                "without_provider": total - with_provider,
            },
            "services_by_category": self.value_counts("count_services_per_category"),
            "services_by_audience": self.value_counts("count_services_per_audience"),
        }

    def list_providers(self) -> list[dict]:
        """List all provider organisations."""

        return [
            {
                "iri": row["provider"],
                "name": row["name"],
                "homepage": row["homepage"],
                "address": {
                    "street": row["street"],
                    "postal_code": row["postal_code"],
                    "city": row["city"],
                },
            }
            for row in self.select("list_providers")
        ]

    def search_by_postal_code(self, postal_code: str) -> list[dict]:
        """Find facilities by German postal code."""

        return [
            {
                "iri": row["facility"],
                "name": row["name"],
                "street": row["street"],
                "postal_code": row["postal_code"],
                "city": row["city"],
                "telephone": row["telephone"],
                "email": row["email"],
                "homepage": row["homepage"],
            }
            for row in self.select("list_facilities_by_postal_code", postal_code=postal_code)
        ]

    def facility_repository(self, city: str):
        """Facilities of a city plus their addresses and providers, shaped for src/fix_first.py."""

        import pandas as pd

        from src.fix_first import FixFirstRepository

        columns = DATASETS["einrichtung"]["columns"]
        # column -> query variable (the query joins multi-valued fields with "; ")
        variables = {
            "iri": "facility",
            "schema:name": "name",
            "schema:alternateName": "alternate_name",
            "schema:telephone": "telephone",
            "schema:email": "email",
            "foaf:homepage": "homepage",
            "schema:mainEntityOfPage": "main_page",
            "schema:category": "category",
            "schema:availableService": "service_description",
            "schema:audience": "audience",
            "schema:accessibilitySummary": "accessibility",
            "schema:openingHours": "opening_hours",
            "schema:parentOrganization": "provider",
            "cdf:parentOrgClassification": "parent_classification",
            "schema:address": "address",
        }

        facilities = self.select("list_facility_quality_fields_by_city", city=city.casefold())

        address_by_iri = {
            row["address"]: {
                "schema:streetAddress": row["street"],
                "schema:postalCode": row["postal_code"],
                "schema:addressLocality": row["city"],
            }
            for row in facilities
            if row["address"]
        }
        provider_by_iri = {
            provider["iri"]: {
                "iri": provider["iri"],
                "schema:name": provider["name"],
                "foaf:homepage": provider["homepage"],
            }
            for provider in self.list_providers()
        }
        einrichtung = pd.DataFrame(
            [{column: row[variables[column]] for column in columns} for row in facilities],
            columns=columns,
            dtype=object,
        )

        return FixFirstRepository(einrichtung, address_by_iri, provider_by_iri)

    def records_to_fix_first(self, city: str, **options) -> dict:
        """Rank the facilities of a city by how much fixing their record matters."""

        from src.fix_first import records_to_fix_first

        result = records_to_fix_first(self.facility_repository(city), **options)
        result["summary"] = {"city": city, **result["summary"]}

        return result

    def compare_facilities(self, facility_1: str, facility_2: str) -> list[dict]:
        """Compare two facilities by name."""

        return [
            {
                "search_name": name,
                "matches": self.get_facility_details(name),
            }
            for name in [facility_1, facility_2]
        ]
