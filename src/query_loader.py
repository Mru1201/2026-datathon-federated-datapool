from pathlib import Path


QUERIES_DIR = Path(__file__).resolve().parent.parent / "queries"


def load(query_name: str) -> str:
    """Read and return the raw text of a .sparql query file."""
    path = QUERIES_DIR / f"{query_name}.sparql"
    return path.read_text(encoding="utf-8")


def build(query_name: str, **params: str) -> str:
    """
    Load a .sparql template and substitute {{key}} placeholders safely.

    Each value is treated as a SPARQL string literal: backslashes, double
    quotes, and newlines are escaped before insertion.  This prevents
    malformed queries caused by user input containing those characters.

    Placeholder syntax uses double braces ({{key}}) to avoid collisions with
    SPARQL ?variables and Python f-string braces.
    """
    template = load(query_name)
    for key, value in params.items():
        escaped = _escape_literal(value)
        template = template.replace("{{" + key + "}}", escaped)
    return template


def _escape_literal(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Query parameter must be a str, got {type(value).__name__}")
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
