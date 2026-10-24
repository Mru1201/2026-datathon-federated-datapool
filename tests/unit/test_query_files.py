"""Query files and query building: offline checks on sparql_queries/ and load_query()."""

import re

import pytest

from src.sparql_client import QUERY_DIR, escape_literal, load_query


def test_escape_literal_escapes_quotes_and_backslashes():
    assert escape_literal('a"b\\c\nd') == 'a\\"b\\\\c\\nd'


def test_load_query_embeds_escaped_city():
    query = load_query("count_facilities_by_city", city='Ber"lin')
    assert '= "Ber\\"lin")' in query, f"city not escaped in query:\n{query}"


def test_load_query_without_required_param_raises():
    with pytest.raises(ValueError, match="city"):
        load_query("count_facilities_by_city")


@pytest.mark.parametrize("path", sorted(QUERY_DIR.glob("*.rq")), ids=lambda p: p.name)
def test_query_files_follow_naming_convention(path):
    match = re.fullmatch(
        r"(count|list|get|ask)_([a-z]+(?:_[a-z]+)*?)(?:_by_([a-z_]+?))?(?:_per_([a-z_]+))?\.rq",
        path.name,
    )
    assert match, f"{path.name} does not follow <action>_<entity>[_by_<param>][_per_<group>].rq (QUERIES.md)"
    text = path.read_text(encoding="utf-8")
    assert "# Params:" in text and "# Used by:" in text, (
        f"{path.name} is missing its '# Params:' / '# Used by:' header comment"
    )
    params = set(re.findall(r"\{\{(\w+)\}\}", text))
    by = match.group(3) or ""
    for param in params:
        assert by.startswith(param), f"{path.name} takes {{{{{param}}}}} but its name has no _by_{param}"
    if not params:
        assert not by, f"{path.name} is named _by_{by} but takes no parameter"
    if match.group(4):
        assert "GROUP BY" in text, f"{path.name} is named _per_{match.group(4)} but has no GROUP BY"
