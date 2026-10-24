import pytest
from src.query_loader import build, _escape_literal


class TestEscapeLiteral:
    def test_plain_string_unchanged(self):
        assert _escape_literal("Berlin") == "Berlin"

    def test_backslash_escaped(self):
        assert _escape_literal("a\\b") == "a\\\\b"

    def test_double_quote_escaped(self):
        assert _escape_literal('say "hi"') == 'say \\"hi\\"'

    def test_newline_escaped(self):
        assert _escape_literal("line1\nline2") == "line1\\nline2"

    def test_injection_attempt_escaped(self):
        injection = '"; DROP ALL GRAPHS; #'
        escaped = _escape_literal(injection)
        assert '"' not in escaped.replace('\\"', "")

    def test_non_string_raises(self):
        with pytest.raises(TypeError):
            _escape_literal(123)  # type: ignore[arg-type]


class TestBuild:
    def test_placeholder_substituted(self):
        sparql = build("count_facilities", city="Berlin")
        assert '"Berlin"' in sparql
        assert "{{city}}" not in sparql

    def test_multiple_placeholders(self):
        sparql = build("search_facilities", city="Hamburg")
        assert '"Hamburg"' in sparql

    def test_missing_query_file_raises(self):
        with pytest.raises(FileNotFoundError):
            build("nonexistent_query", foo="bar")
