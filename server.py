import json
import math
import sys

from mcp.server.fastmcp import FastMCP

from src.sparql_client import SparqlClient


# --------------------------------------------------
# Data source: live SPARQL API (see QUERIES.md)
# --------------------------------------------------

sparql = SparqlClient()


# --------------------------------------------------
# MCP server
# --------------------------------------------------

mcp = FastMCP("AWO MCP")


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def normalize_nan(value):
    """Convert pandas/NumPy NaN values to JSON-compatible None."""

    if isinstance(value, dict):
        return {
            key: normalize_nan(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            normalize_nan(item)
            for item in value
        ]

    if isinstance(value, float) and math.isnan(value):
        return None

    return value


def to_json(data) -> str:
    """Convert Python data to a JSON string."""

    return json.dumps(
        normalize_nan(data),
        ensure_ascii=False,
        indent=2,
    )


# --------------------------------------------------
# MCP Tools
# --------------------------------------------------

@mcp.tool()
def count_facilities(city: str) -> int:
    """
    Count facilities in a city in the federated directory of
    social support services in Germany (live SPARQL API).

    Args:
        city: City name, for example "Berlin".
    """

    return sparql.count_facilities(city)

@mcp.tool()
def detect_duplicates() -> str:
    """
    Detect duplicate entries in all datasets of the directory
    (facilities, addresses, services, providers).

    A duplicate group is two or more entries whose values are
    identical in every column except their IRI.

    Returns:
        JSON per dataset: number of occurrences, the IRIs of the
        duplicated entries and the shared column values.
    """

    results = sparql.detect_duplicates()

    return to_json(results)

@mcp.tool()
def search_facilities(city: str) -> str:
    """
    Search for facilities in a city.

    Args:
        city: City name, for example "Berlin".

    Returns:
        JSON containing matching facilities and their basic contact/address information.
    """

    results = sparql.search_facilities(city)

    return to_json(results)


@mcp.tool()
def get_facility_details(name: str) -> str:
    """
    Find facilities by name and return detailed information.

    Args:
        name: Full or partial facility name.

    Returns:
        JSON containing facility details, address, provider,
        and the facility's service description.
    """

    results = sparql.get_facility_details(name)

    return to_json(results)


@mcp.tool()
def search_services(query: str) -> str:
    """
    Search the structured service catalogue.

    Args:
        query: Search term, such as "Senioren", "Pflege", or "Beratung".

    Returns:
        JSON containing matching services.
    """

    results = sparql.search_services(query)

    return to_json(results)

@mcp.tool()
def check_completeness() -> str:
    """
    Check completeness of all datasets (facilities, addresses,
    services, providers).

    A value is missing when it is absent or only whitespace.

    Returns:
        JSON containing dataset-level and column-level
        completeness statistics.
    """

    results = sparql.check_completeness()

    return to_json(results)

@mcp.tool()
def generate_statistics() -> str:
    """
    Generate statistics for the datasets of the directory.

    Returns:
        JSON containing dataset sizes, facility statistics,
        service statistics, and relationship statistics.
    """

    results = sparql.generate_statistics()

    return to_json(results)

@mcp.tool()
def compare_facilities(
    facility_1: str,
    facility_2: str,
) -> str:
    """
    Compare two facilities by name.

    Args:
        facility_1: Full or partial name of the first facility.
        facility_2: Full or partial name of the second facility.

    Returns:
        JSON containing the details of both facilities.
    """

    results = sparql.compare_facilities(
        facility_1,
        facility_2,
    )

    return to_json(results)

# --------------------------------------------------
# Run server
# --------------------------------------------------

if __name__ == "__main__":
    print("AWO MCP server starting...", file=sys.stderr)
    mcp.run()

    
