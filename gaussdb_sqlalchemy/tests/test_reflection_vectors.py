"""Regression coverage for DBAPI catalog arrays and GaussDB int2vector text."""

import pytest

from gaussdb_sqlalchemy.base import (
    GaussDBDialect,
    GaussDBDialect_psycopg2,
    _parse_catalog_int_vector,
)


class CatalogResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def fetchall(self):
        return self.rows


class CatalogConnection:
    """Return realistic catalog rows, recording attribute lookup order."""

    def __init__(self, row):
        self.row = row
        self.lookups = []

    def execute(self, statement, params):
        sql = str(statement)
        if "pg_catalog.pg_attribute" in sql:
            key = (params["relid"], params["attnum"])
            self.lookups.append(key)
            name = f"col_{key[0]}_{key[1]}".encode("ascii")
            return CatalogResult([{"attname": name}])
        assert "pg_catalog.pg_constraint" in sql or "pg_catalog.pg_index" in sql
        assert params == {"table_name": "sample", "schema": "public"}
        return CatalogResult([self.row])


@pytest.fixture(params=[GaussDBDialect, GaussDBDialect_psycopg2])
def dialect(request):
    result = request.param()
    result.gaussdb_compatibility = "M"
    result.default_schema_name = "public"
    return result


@pytest.mark.parametrize("conkey", [[2], (2,), "{2}", "{[2]}", b"{[2]}"])
def test_unique_constraint_single_column_report_regression(dialect, conkey):
    connection = CatalogConnection({"name": "uq_sample", "conkey": conkey, "conrelid": 101})
    assert dialect.get_unique_constraints(connection, "sample") == [{
        "name": "uq_sample",
        "column_names": ["col_101_2"],
        "duplicates_index": None,
        "comment": None,
    }]
    assert connection.lookups == [(101, 2)]


@pytest.mark.parametrize("conkey", [[3, 2], (3, 2), "{3,2}", "{[3,2]}"])
def test_unique_constraint_preserves_composite_key_order(dialect, conkey):
    connection = CatalogConnection({"name": "uq_sample", "conkey": conkey, "conrelid": 101})
    constraints = dialect.get_unique_constraints(connection, "sample")
    assert constraints[0]["column_names"] == ["col_101_3", "col_101_2"]
    assert connection.lookups == [(101, 3), (101, 2)]


@pytest.mark.parametrize("conkey,confkey", [
    ([3, 2], (7, 5)),
    (b"{3,2}", "{[7,5]}"),
    ("{[3],[2]}", bytearray(b"{7,5}")),
])
def test_foreign_key_preserves_paired_column_order(dialect, conkey, confkey):
    connection = CatalogConnection({
        "name": "fk_sample", "conkey": conkey, "confkey": confkey,
        "conrelid": 101, "confrelid": 202,
        "ref_schema": "other_schema", "ref_table": "parent",
    })
    foreign_key, = dialect.get_foreign_keys(connection, "sample")
    assert foreign_key["constrained_columns"] == ["col_101_3", "col_101_2"]
    assert foreign_key["referred_columns"] == ["col_202_7", "col_202_5"]
    assert foreign_key["referred_schema"] == "other_schema"
    assert foreign_key["referred_table"] == "parent"
    assert connection.lookups == [(101, 3), (101, 2), (202, 7), (202, 5)]


@pytest.mark.parametrize("mode", ["A", "B", "M"])
@pytest.mark.parametrize("indkey", [[3, 0, 2], (3, 0, 2), b"3 0 2", "{3,0,2}"])
def test_index_reflection_accepts_dbapi_vectors(dialect, mode, indkey):
    dialect.gaussdb_compatibility = mode
    connection = CatalogConnection({
        "index_name": "ix_sample", "is_unique": False, "is_valid": True,
        "indkey": indkey, "indrelid": 101, "am_name": "btree",
    })
    index, = dialect.get_indexes(connection, "sample")
    assert index["column_names"] == ["col_101_3", "col_101_2"]
    assert index["unique"] is False
    # A zero is an expression slot, not a column attribute number.
    assert connection.lookups == [(101, 3), (101, 2)]


@pytest.mark.parametrize("value,expected", [
    ([], []), ((), []), ("", []), ("{}", []), ("[]", []),
    ([2, "3", b"4"], [2, 3, 4]),
    (" 3  2 \t -1 +0 ", [3, 2, -1, 0]),
    ("{ [3, 2] }", [3, 2]),
    ("{[3], [2]}", [3, 2]),
    (memoryview(b"{3,2}"), [3, 2]),
])
def test_catalog_vector_supported_values(value, expected):
    assert _parse_catalog_int_vector(value) == expected


@pytest.mark.parametrize("value", [
    None, True, 2.5, [True], [2.5], [None], [[2]], {2, 3},
    "{2,}", "{,2}", "{2,,3}", "{2,3", "2,3}", "{[2]",
    "{{2,3}}", "[2,3", "2 3,4", "{2,NULL}", "2;DROP TABLE t", b"\xff",
])
def test_catalog_vector_rejects_malformed_values(value):
    with pytest.raises(ValueError, match="catalog integer vector"):
        _parse_catalog_int_vector(value)


def test_unique_constraint_does_not_silently_drop_malformed_columns(dialect):
    connection = CatalogConnection({"name": "uq_sample", "conkey": "{3,bad,2}", "conrelid": 101})
    with pytest.raises(ValueError, match="catalog integer vector"):
        dialect.get_unique_constraints(connection, "sample")
    assert not connection.lookups
