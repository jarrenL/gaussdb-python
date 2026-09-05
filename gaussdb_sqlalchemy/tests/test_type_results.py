"""DBAPI-shaped result regressions for both supported drivers."""
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import JSON, LargeBinary, select, column
from sqlalchemy.dialects.postgresql import JSON as PGJSON, JSONB, BYTEA

from gaussdb_sqlalchemy.base import GaussDBDialect, GaussDBDialect_psycopg2


@pytest.fixture(params=[GaussDBDialect, GaussDBDialect_psycopg2])
def dialect(request):
    return request.param()


@pytest.mark.parametrize("type_", [JSON(), PGJSON(), JSONB()])
@pytest.mark.parametrize("value", [
    {"nested": [1, None, True, {"text": "中文"}]}, [1, "two"],
    "plain text", "123", "null", '{"still": "a string"}', "", 123,
    1.25, True, False, None,
])
def test_native_json_is_not_deserialized_twice(dialect, type_, value):
    process = type_.dialect_impl(dialect).result_processor(dialect, None)
    actual = process(value) if process else value
    assert actual == value
    assert type(actual) is type(value)


@pytest.mark.parametrize("type_", [JSON(), PGJSON(), JSONB()])
def test_json_bind_serializer_still_runs(dialect, type_):
    dialect._json_serializer = Mock(return_value='{"sent":true}')
    process = type_.dialect_impl(dialect).bind_processor(dialect)
    assert process({"sent": True}) == '{"sent":true}'
    dialect._json_serializer.assert_called_once_with({"sent": True})


@pytest.mark.parametrize("type_", [LargeBinary(), BYTEA()])
@pytest.mark.parametrize("value, expected", [
    (None, None), (b"", b""), ("", b""),
    ("000147617573734442FF10", b"\x00\x01GaussDB\xff\x10"),
    (r"\x00ff", b"\x00\xff"), ("0x00Ff", b"\x00\xff"),
    (b"deadbeef", b"deadbeef"), (bytearray(b"00ff"), b"00ff"),
    (memoryview(b"\x00\xff"), b"\x00\xff"),
])
def test_binary_result_preserves_bytes_and_decodes_hex(dialect, type_, value, expected):
    process = type_.dialect_impl(dialect).result_processor(dialect, None)
    actual = process(value) if process else value
    assert actual == expected
    if expected is not None:
        assert isinstance(actual, bytes)


@pytest.mark.parametrize("value", ["abc", "not-hex", "00 11", "xx00"])
def test_invalid_binary_text_fails_explicitly(dialect, value):
    process = LargeBinary().dialect_impl(dialect).result_processor(dialect, None)
    with pytest.raises(ValueError, match="hex"):
        process(value)


def test_json_custom_loader_is_connection_local_psycopg2():
    dialect = GaussDBDialect_psycopg2(json_deserializer=Mock())
    connection = object()
    # Match the DBAPI registration contract without requiring libpq to load.
    extras = Mock()
    with patch.dict("sys.modules", {"psycopg2.extras": extras}):
        dialect.on_connect()(connection)
    extras.register_default_json.assert_called_once_with(
        connection, loads=dialect._json_deserializer)
    extras.register_default_jsonb.assert_called_once_with(
        connection, loads=dialect._json_deserializer)


def test_json_custom_loader_is_connection_local_psycopg3():
    dialect = GaussDBDialect(json_deserializer=Mock())
    connection = object()
    json_module = Mock()
    with patch.dict("sys.modules", {"gaussdb.types.json": json_module}):
        dialect.on_connect()(connection)
    json_module.set_json_loads.assert_called_once_with(
        dialect._json_deserializer, connection)


def test_json_operators_and_binary_ddl_keep_pg_types(dialect):
    assert " -> " in str(select(column("payload", JSON())["key"]).compile(dialect=dialect))
    assert JSONB().dialect_impl(dialect).compile(dialect=dialect) == "JSONB"
    assert BYTEA().dialect_impl(dialect).compile(dialect=dialect) == "BYTEA"
