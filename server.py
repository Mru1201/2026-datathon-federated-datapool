"""AWO MCP server: exposes the federated directory of social support services as MCP tools.

Each tool calls one SparqlClient method (src/sparql_client.py), which runs the queries in
sparql_queries/ against the live SPARQL endpoint. Run with `python server.py` (stdio).
"""

import json
import sys

from mcp.server.mcpserver import MCPServer as FastMCP

from src.sparql_client import SparqlClient

sparql = SparqlClient()

mcp = FastMCP("AWO MCP")


def to_json(data) -> str:
    """Serialize a tool result; umlauts stay readable instead of being \\u-escaped."""

    return json.dumps(data, ensure_ascii=False, indent=2)


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

    return to_json(sparql.detect_duplicates())


@mcp.tool()
def search_facilities(city: str) -> str:
    """
    Search for facilities in a city.

    Args:
        city: City name, for example "Berlin".

    Returns:
        JSON containing matching facilities and their basic contact/address information.
    """

    return to_json(sparql.search_facilities(city))


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

    return to_json(sparql.get_facility_details(name))


@mcp.tool()
def search_services(query: str) -> str:
    """
    Search the structured service catalogue.

    Args:
        query: Search term, such as "Senioren", "Pflege", or "Beratung".

    Returns:
        JSON containing matching services.
    """

    return to_json(sparql.search_services(query))


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

    return to_json(sparql.check_completeness())


@mcp.tool()
def generate_statistics() -> str:
    """
    Generate statistics for the datasets of the directory.

    Returns:
        JSON containing dataset sizes, facility statistics,
        service statistics, and relationship statistics.
    """

    return to_json(sparql.generate_statistics())


@mcp.tool()
def compare_facilities(facility_1: str, facility_2: str) -> str:
    """
    Compare two facilities by name.

    Args:
        facility_1: Full or partial name of the first facility.
        facility_2: Full or partial name of the second facility.

    Returns:
        JSON containing the details of both facilities.
    """

    return to_json(sparql.compare_facilities(facility_1, facility_2))


@mcp.tool()
def list_providers() -> str:
    """
    List all provider organisations in the federated directory.

    Returns:
        JSON containing provider names, websites, and addresses.
    """

    return to_json(sparql.list_providers())


@mcp.tool()
def search_by_postal_code(postal_code: str) -> str:
    """
    Find welfare facilities by German postal code.

    Args:
        postal_code: Five-digit German postal code, for example "10115".

    Returns:
        JSON containing facilities located in that postal code area.
    """

    return to_json(sparql.search_by_postal_code(postal_code))


@mcp.tool()
def records_to_fix_first(
    city: str = "Berlin",
    provider: str | None = None,
    n: int = 10,
    bucket: str | None = None,
    group_by: str | None = None,
    focus: str | None = None,
    explain: bool = False,
) -> str:
    """
    Rank the facility records of one city by how much fixing them matters, for
    data maintainers (not for people looking for help). Use this when asked
    which records to fix first, what is wrong with the data, which records may
    not belong in the directory, whom to contact about missing information, or
    how the priority or ranking of records is calculated (then set explain to
    true). All counts and percentages in the result cover only the requested
    city, never the whole directory.

    Each record is placed in a bucket: complete_key_field (informative but
    missing phone, email, hours or address), repair (a value is broken, such as
    a phone number that lost its leading zero), ask_provider (the provider can
    fill the gap), enrich_from_source (almost empty but a source page exists),
    scope_check (may not be a service, for example a church body),
    junk_or_duplicate, needs_research (almost empty, no lead) and minor_gaps.
    Each record has a priority tier (high, medium or low), and results are
    ordered from most to least important. The numeric score is not shown by
    default, because small score differences are not meaningful.

    Args:
        city: City to check, for example "Berlin" (default). Matches exactly.
        provider: Part of a provider name, or "unassigned" for facilities with
            no provider link.
        n: How many records to return (default 10).
        bucket: Only return one bucket, for example "scope_check".
        group_by: Use "provider" to get batches for outreach (one request per
            provider) instead of single records.
        focus: Use "urgent" to only return services people may urgently depend
            on (addiction help, homelessness, crisis, debt counselling).
        explain: Set to true only when the user asks how priority is determined
            or why one record ranks above another. It adds the numeric score
            and a breakdown (missing field weight, bonuses and bucket
            multiplier) to each record.

    How to answer: use only facts from the tool result, and do not add outside
    knowledge such as dates, seasons or locations, and do not claim something
    about all records unless the summary says so. Lead with the conclusion in
    one or two sentences, then answer only what was asked (about 120 words plus
    any table). Use a table only when listing several records or providers,
    with just the columns that matter (name, priority, what is missing, where
    to look). When listing records, show every returned row in rank order and
    keep the rank numbers, so any text can refer to them. Take counts from the summary (for example `shown` and
    `urgent_in_matching_records`) instead of counting rows yourself. Explain
    how priority is calculated, or go into detail, only when the user asks.

    Returns:
        JSON with a summary, a projected coverage gain (a projection, not a
        measured improvement), and either ranked records with reasons, leads
        and next steps, or provider batches.
    """

    return to_json(
        sparql.records_to_fix_first(
            city,
            provider=provider,
            n=n,
            bucket=bucket,
            group_by=group_by,
            focus=focus,
            explain=explain,
        )
    )


if __name__ == "__main__":
    # stdout carries the MCP protocol, so log to stderr.
    print("AWO MCP server starting...", file=sys.stderr)
    mcp.run()
