"""Catalog mode names must not be confused with their first letters."""
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import InvalidRequestError

from gaussdb_sqlalchemy.base import (
    GaussDBDialect, GaussDBDialect_psycopg2, _detect_compatibility,
)


@pytest.mark.parametrize("raw,expected", [
    ("A", "A"), ("ORA", "A"), (" ora ", "A"),
    ("B", "B"), ("MYSQL", "B"), (" MySQL ", "B"),
    ("M", "M"), (" m ", "M"), ("PG", "PG"), (" pg ", "PG"),
    (b"ORA", "A"), (bytearray(b"MYSQL"), "B"), (memoryview(b"PG"), "PG"),
])
def test_complete_catalog_name(raw, expected):
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = raw
    assert _detect_compatibility(connection) == expected


@pytest.mark.parametrize("raw", [
    None, "", " ", "APPLE", "BAD", "MYSQL8", "MYSTERY", "POSTGRESQL",
    "P", "C", "TD", 1, ["ORA"], b"\xff", "ORA\x00",
])
def test_unknown_catalog_mode_is_not_guessed(raw):
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = raw
    with pytest.raises(InvalidRequestError, match="datcompatibility"):
        _detect_compatibility(connection)


@pytest.mark.parametrize("dialect_cls", [GaussDBDialect, GaussDBDialect_psycopg2])
@pytest.mark.parametrize("raw,expected,quote,returning", [
    ("ORA", "A", '"', True), ("MYSQL", "B", '"', True),
    ("M", "M", "`", False), ("PG", "PG", '"', True),
])
def test_initialize_applies_the_correct_mode_features(dialect_cls, raw, expected, quote, returning):
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = raw
    dialect = dialect_cls()
    with patch("sqlalchemy.dialects.postgresql.base.PGDialect.initialize"):
        dialect.initialize(connection)
    assert dialect.gaussdb_compatibility == expected
    assert dialect.identifier_preparer.initial_quote == quote
    assert dialect.insert_returning is returning
    assert dialect.supports_native_boolean is returning
