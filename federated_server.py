import json
import logging
import sys

import httpx
from fastmcp import FastMCP

from src.federated_config import settings
from src.sparql_client import SparqlClient
from src.sparql_repository import SparqlRepository


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Initialise HTTP client and repository (once at server startup)
# ------------------------------------------------------------------

_http = httpx.Client(timeout=settings.sparql_timeout)
_sparql = SparqlClient(_http, settings.sparql_endpoint)
repository = SparqlRepository(_sparql, cache_ttl=settings.cache_ttl)


# ------------------------------------------------------------------
# MCP server
# ------------------------------------------------------------------

mcp = FastMCP(settings.server_name)


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def to_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------
# MCP Tools
# ------------------------------------------------------------------

@mcp.tool()
def count_facilities(city: str) -> int:
    """
    Count welfare facilities in a city across all federated sources.

    Args:
        city: City name, for example "Berlin".
    """
    return repository.count_facilities(city)


@mcp.tool()
def search_facilities(city: str) -> str:
    """
    Search for welfare facilities in a city.

    Args:
        city: City name, for example "Berlin".

    Returns:
        JSON containing matching facilities and their basic contact/address
        information.
    """
    return to_json(repository.search_facilities(city))


@mcp.tool()
def get_facility_details(name: str) -> str:
    """
    Find welfare facilities by name and return detailed information.

    Args:
        name: Full or partial facility name.

    Returns:
        JSON containing facility details including address, provider, and
        category.
    """
    return to_json(repository.get_facility_details(name))


@mcp.tool()
def search_services(query: str) -> str:
    """
    Search the federated service catalogue by keyword.

    Args:
        query: Search term, such as "Suchtberatung", "Pflege", or "Kinder".

    Returns:
        JSON containing matching services with their category and audience.
    """
    return to_json(repository.search_services(query))


@mcp.tool()
def generate_statistics() -> str:
    """
    Generate aggregate statistics for the federated welfare directory.

    Returns:
        JSON containing facility counts grouped by city, category, and
        provider organisation.
    """
    return to_json(repository.generate_statistics())


@mcp.tool()
def compare_facilities(facility_1: str, facility_2: str) -> str:
    """
    Compare two welfare facilities by name.

    Args:
        facility_1: Full or partial name of the first facility.
        facility_2: Full or partial name of the second facility.

    Returns:
        JSON containing the details of both facilities side by side.
    """
    return to_json(repository.compare_facilities(facility_1, facility_2))


@mcp.tool()
def list_providers() -> str:
    """
    List all provider organisations in the federated directory.

    Returns:
        JSON containing provider names, websites, and addresses.
    """
    return to_json(repository.list_providers())


@mcp.tool()
def search_by_postal_code(postal_code: str) -> str:
    """
    Find welfare facilities by German postal code.

    Args:
        postal_code: Five-digit German postal code, for example "10115".

    Returns:
        JSON containing facilities located in that postal code area.
    """
    return to_json(repository.search_by_postal_code(postal_code))


# ------------------------------------------------------------------
# Run server
# ------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Federated Welfare Directory MCP server starting...")
    logger.info("SPARQL endpoint: %s", settings.sparql_endpoint)
    mcp.run()
