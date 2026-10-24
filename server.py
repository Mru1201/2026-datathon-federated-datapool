import json
import math
from pathlib import Path
import sys

import pandas as pd
from fastmcp import FastMCP

from src.data_loader import DataLoader
from src.data_repository import DataRepository


# --------------------------------------------------
# Configuration
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


# --------------------------------------------------
# Load data
# --------------------------------------------------

loader = DataLoader(DATA_DIR)
datasets = loader.load_all()

repository = DataRepository(datasets)


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
    Count AWO facilities in a city.

    Args:
        city: City name, for example "Berlin".
    """

    return repository.count_facilities(city)

@mcp.tool()
def detect_duplicates() -> str:
    """
    Detect exact duplicate rows in all AWO datasets.

    A duplicate means that every column in a row is identical
    to another row in the same dataset.

    Returns:
        JSON containing the complete duplicated rows and
        their number of occurrences.
    """

    results = repository.detect_duplicates()

    return to_json(results)

@mcp.tool()
def search_facilities(city: str) -> str:
    """
    Search for AWO facilities in a city.

    Args:
        city: City name, for example "Berlin".

    Returns:
        JSON containing matching facilities and their basic contact/address information.
    """

    results = repository.search_facilities(city)

    return to_json(results)


@mcp.tool()
def get_facility_details(name: str) -> str:
    """
    Find AWO facilities by name and return detailed information.

    Args:
        name: Full or partial facility name.

    Returns:
        JSON containing facility details, address, provider,
        and the facility's service description.
    """

    results = repository.get_facility_details(name)

    return to_json(results)


@mcp.tool()
def search_services(query: str) -> str:
    """
    Search the structured AWO service catalogue.

    Args:
        query: Search term, such as "Senioren", "Pflege", or "Beratung".

    Returns:
        JSON containing matching services.
    """

    results = repository.search_services(query)

    return to_json(results)

@mcp.tool()
def check_completeness() -> str:
    """
    Check completeness of all AWO datasets.

    Missing values include both NaN and empty/whitespace-only
    strings.

    Returns:
        JSON containing dataset-level and column-level
        completeness statistics.
    """

    results = repository.check_completeness()

    return to_json(results)

@mcp.tool()
def generate_statistics() -> str:
    """
    Generate statistics for the AWO datasets.

    Returns:
        JSON containing dataset sizes, facility statistics,
        service statistics, and relationship statistics.
    """

    results = repository.generate_statistics()

    return to_json(results)

@mcp.tool()
def compare_facilities(
    facility_1: str,
    facility_2: str,
) -> str:
    """
    Compare two AWO facilities by name.

    Args:
        facility_1: Full or partial name of the first facility.
        facility_2: Full or partial name of the second facility.

    Returns:
        JSON containing the details of both facilities.
    """

    results = repository.compare_facilities(
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

    
