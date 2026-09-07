"""Keep physical index system attributes out of logical reflected columns."""

import pytest
from sqlalchemy.dialects.postgresql.base import PGDialect

from gaussdb_sqlalchemy.base import GaussDBDialect, GaussDBDialect_psycopg2


class CatalogResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def fetchall(self):
        return self.rows


class CatalogConnection:
    """Model conkey separately from a backing index's physical indkey."""

    attributes = {
        -1: "ctid",
        -3: "xmin",
        -11: "xc_node_hash",
        1: "id",
        2: "code",
        3: "tenant",
        # A real user column must not be removed just because of its name.
        4: "xc_node_hash",
    }

    def __init__(self, conkey=(2,), indkey=(2, -1, -3, -11), empty=False,
                 comment=None):
        self.constraint_rows = [] if empty else [{
            "name": "uq_sample",
            "conkey": conkey,
            "conrelid": 101,
            "comment": comment,
        }]
        self.index_rows = [] if empty else [{
            "index_name": "uq_sample",
            "is_unique": True,
            "is_valid": True,
            "indkey": indkey,
            "indrelid": 101,
            "am_name": "btree",
        }]
        self.lookups = []
        self.catalog_reads = []

    def execute(self, statement, params):
        sql = str(statement)
        if "pg_catalog.pg_attribute" in sql:
            assert params["relid"] == 101
            self.lookups.append(params["attnum"])
            return CatalogResult([{
                "attname": self.attributes[params["attnum"]].encode("ascii"),
            }])
        assert params == {"table_name": "sample", "schema": "public"}
        if "pg_catalog.pg_constraint" in sql:
            self.catalog_reads.append("constraint")
            return CatalogResult(self.constraint_rows)
        assert "pg_catalog.pg_index" in sql
        self.catalog_reads.append("index")
        return CatalogResult(self.index_rows)

    def physical_unique_constraints(self):
        """Represent the inherited PG path that exposed physical index keys."""
        return [{
            "name": row["index_name"],
            "column_names": [self.attributes[num] for num in row["indkey"]],
            "duplicates_index": None,
        } for row in self.index_rows]


@pytest.fixture(params=[GaussDBDialect, GaussDBDialect_psycopg2])
def dialect(request):
    instance = request.param()
    instance.default_schema_name = "public"
    return instance


@pytest.fixture(params=["A", "B", "M", "PG"])
def mode(request, dialect):
    dialect.gaussdb_compatibility = request.param
    return request.param


@pytest.fixture
def inherited_physical_constraint_path(monkeypatch):
    # Model the regression at the PG boundary without depending on a specific
    # SQLAlchemy version's private query builders or its required server state.
    def single(self, connection, table_name, schema=None, **kw):
        return connection.physical_unique_constraints()

    def multi(self, connection, schema=None, filter_names=None, **kw):
        return {(schema, name): connection.physical_unique_constraints()
                for name in filter_names}

    monkeypatch.setattr(PGDialect, "get_unique_constraints", single)
    monkeypatch.setattr(PGDialect, "get_multi_unique_constraints", multi)


def reflect_constraints(dialect, connection, entrypoint):
    if entrypoint == "single":
        return dialect.get_unique_constraints(connection, "sample")
    reflected = dict(dialect.get_multi_unique_constraints(
        connection, schema="public", filter_names=["sample"],
    ))
    assert list(reflected) == [("public", "sample")]
    return reflected[("public", "sample")]


@pytest.mark.parametrize("entrypoint", ["single", "multi"])
@pytest.mark.parametrize("conkey", [[2], "{[2]}", b"{2}"])
@pytest.mark.parametrize("mode", ["B", "M"], indirect=True)
def test_unique_uses_logical_conkey_not_physical_index(
    dialect, mode, inherited_physical_constraint_path, entrypoint, conkey,
):
    connection = CatalogConnection(conkey=conkey)
    constraints = reflect_constraints(dialect, connection, entrypoint)
    assert constraints[0]["name"] == "uq_sample"
    assert constraints[0]["column_names"] == ["code"]
    assert connection.lookups == [2]
    assert connection.catalog_reads == ["constraint"]


@pytest.mark.parametrize("entrypoint", ["single", "multi"])
@pytest.mark.parametrize("mode", ["B", "M"], indirect=True)
def test_unique_preserves_logical_order_and_system_like_user_name(
    dialect, mode, inherited_physical_constraint_path, entrypoint,
):
    # Physical order and members differ; conkey is the logical SQL constraint.
    connection = CatalogConnection(conkey=[3, 4, 2], indkey=(2, -11, 4, -1, 3))
    constraints = reflect_constraints(dialect, connection, entrypoint)
    assert constraints[0]["column_names"] == ["tenant", "xc_node_hash", "code"]
    assert connection.lookups == [3, 4, 2]
    assert connection.catalog_reads == ["constraint"]


@pytest.mark.parametrize("entrypoint", ["single", "multi"])
@pytest.mark.parametrize("mode", ["B", "M"], indirect=True)
def test_empty_unique_constraints_use_same_catalog_path(
    dialect, mode, inherited_physical_constraint_path, entrypoint,
):
    connection = CatalogConnection(empty=True)
    assert reflect_constraints(dialect, connection, entrypoint) == []
    assert connection.lookups == []
    assert connection.catalog_reads == ["constraint"]


@pytest.mark.parametrize("entrypoint", ["single", "multi"])
@pytest.mark.parametrize("mode", ["B", "M"], indirect=True)
@pytest.mark.parametrize("comment", [None, "Business code", b"Business code"])
def test_unique_constraint_comment_is_preserved(
    dialect, mode, inherited_physical_constraint_path, entrypoint, comment,
):
    connection = CatalogConnection(comment=comment)
    constraint, = reflect_constraints(dialect, connection, entrypoint)
    expected = comment.decode() if isinstance(comment, bytes) else comment
    assert constraint["comment"] == expected
    assert constraint["column_names"] == ["code"]


@pytest.mark.parametrize("mode", ["B", "M"], indirect=True)
def test_empty_filter_names_does_not_reflect_all_tables(dialect, mode, monkeypatch):
    connection = CatalogConnection()

    def unexpected_enumeration(*args, **kwargs):
        pytest.fail("An empty filter_names must not enumerate all tables")

    monkeypatch.setattr(dialect, "get_table_names", unexpected_enumeration)
    assert dict(dialect.get_multi_unique_constraints(
        connection, schema="public", filter_names=[],
    )) == {}
    assert connection.catalog_reads == []
    assert connection.lookups == []


@pytest.mark.parametrize("entrypoint", ["single", "multi"])
@pytest.mark.parametrize("mode", ["A", "PG"], indirect=True)
def test_unrelated_unique_modes_still_delegate_to_postgresql(
    dialect, mode, inherited_physical_constraint_path, entrypoint,
):
    connection = CatalogConnection()
    assert reflect_constraints(dialect, connection, entrypoint) == (
        connection.physical_unique_constraints()
    )
    assert connection.catalog_reads == []
    assert connection.lookups == []


@pytest.mark.parametrize("entrypoint", ["single", "multi"])
@pytest.mark.parametrize("indkey", [
    [3, -1, 4, -3, 0, 2, -11],
    b"3 -1 4 -3 0 2 -11",
    "{3,-1,4,-3,0,2,-11}",
])
def test_indexes_omit_negative_attributes_not_named_user_columns(
    dialect, mode, entrypoint, indkey,
):
    connection = CatalogConnection(indkey=indkey)
    if entrypoint == "single":
        indexes = dialect.get_indexes(connection, "sample")
    else:
        reflected = dict(dialect.get_multi_indexes(
            connection, schema="public", filter_names=["sample"],
        ))
        assert list(reflected) == [("public", "sample")]
        indexes = reflected[("public", "sample")]
    assert indexes[0]["column_names"] == ["tenant", "xc_node_hash", "code"]
    assert indexes[0]["unique"] is True
    # Zero remains the existing skipped expression slot; no system lookups.
    assert connection.lookups == [3, 4, 2]
    assert connection.catalog_reads == ["index"]
