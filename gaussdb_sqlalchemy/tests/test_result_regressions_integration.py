"""Live regressions for row counts, native JSON, binary data, and catalog arrays.

Uses the same URL matrix and cleanup rules as the basic 26 live cases.
"""
import json

import pytest
from sqlalchemy import (
    Column, Integer, JSON, LargeBinary, MetaData, Table, UniqueConstraint,
    bindparam, create_engine, event, inspect, literal, select,
)
from sqlalchemy.exc import IntegrityError

from .test_dialect_integration import engine, _table_name, _drop_table  # noqa: F401


@pytest.mark.integration
def test_live_insert_rowcount_survives_cursor_close(engine):
    name = _table_name("gdb_sa_live_insert_count")
    table = Table(name, MetaData(), Column("id", Integer, primary_key=True, autoincrement=False),
                  Column("value", Integer))
    observed = []

    def after_execute(conn, cursor, statement, parameters, context, executemany):
        if context.isinsert:
            observed.append(cursor.rowcount)

    event.listen(engine, "after_cursor_execute", after_execute)
    try:
        table.create(engine)
        with engine.begin() as conn:
            for count in (1, 2, 5):
                parameters = [{"id": count * 10 + i, "value": i} for i in range(count)]
                result = conn.execute(table.insert(), parameters)
                # Read the DBAPI count before SQLAlchemy closes its cursor.
                assert observed[-1] == count
                assert result.rowcount == observed[-1]
                result.close()
                assert result.rowcount == count
    finally:
        event.remove(engine, "after_cursor_execute", after_execute)
        _drop_table(engine, name)


@pytest.mark.integration
def test_live_dml_rowcount_uses_affected_rows_not_parameter_count(engine):
    name = _table_name("gdb_sa_live_affected_count")
    table = Table(name, MetaData(), Column("id", Integer, primary_key=True, autoincrement=False),
                  Column("value", Integer))
    try:
        table.create(engine)
        conditional_insert = table.insert().from_select(
            ["id", "value"],
            select(bindparam("new_id"), bindparam("new_value")).where(bindparam("enabled") == literal(1)),
        )
        with engine.begin() as conn:
            no_rows = conn.execute(conditional_insert, [
                {"new_id": 90, "new_value": 0, "enabled": 0},
                {"new_id": 91, "new_value": 0, "enabled": 0},
            ])
            assert no_rows.rowcount == 0
            mixed = conn.execute(conditional_insert, [
                {"new_id": 1, "new_value": 10, "enabled": 1},
                {"new_id": 2, "new_value": 20, "enabled": 0},
                {"new_id": 3, "new_value": 30, "enabled": 1},
            ])
            assert mixed.rowcount == 2  # Three parameter sets, only two rows.
            update = table.update().where(table.c.id == bindparam("match_id")).values(value=99)
            assert conn.execute(update, [{"match_id": 1}, {"match_id": 2}, {"match_id": 3}]).rowcount == 2
            delete = table.delete().where(table.c.id == bindparam("match_id"))
            assert conn.execute(delete, [{"match_id": 1}, {"match_id": 2}]).rowcount == 1
            assert conn.execute(select(table.c.id)).scalars().all() == [3]
    finally:
        _drop_table(engine, name)


@pytest.mark.integration
def test_live_json_objects_and_scalars(engine):
    name = _table_name("gdb_sa_live_json_scalars")
    table = Table(name, MetaData(), Column("id", Integer), Column("payload", JSON))
    values = [{"items": [1, None, {"中文": True}]}, [False, 2], "hello",
              "123", "null", '{"still":"a string"}', "", 123, 1.25, True, False, None]
    try:
        table.create(engine)
        with engine.begin() as conn:
            conn.execute(table.insert(), [{"id": i, "payload": v} for i, v in enumerate(values)])
        with engine.connect() as conn:
            actual = conn.execute(select(table.c.payload).order_by(table.c.id)).scalars().all()
        assert actual == values
        assert [type(v) for v in actual] == [type(v) for v in values]
    finally:
        _drop_table(engine, name)


@pytest.mark.integration
def test_live_json_custom_deserializer(engine):
    name = _table_name("gdb_sa_live_json_custom")
    table = Table(name, MetaData(), Column("id", Integer), Column("payload", JSON))
    custom = create_engine(engine.url, json_deserializer=lambda value: {"decoded": json.loads(value)})
    try:
        table.create(engine)
        with engine.begin() as conn:
            conn.execute(table.insert(), {"id": 1, "payload": {"a": 1}})
        with custom.connect() as conn:
            assert conn.execute(select(table.c.payload)).scalar_one() == {"decoded": {"a": 1}}
    finally:
        custom.dispose()
        _drop_table(engine, name)


@pytest.mark.integration
def test_live_binary_bytes_type_and_contents(engine):
    name = _table_name("gdb_sa_live_binary_types")
    table = Table(name, MetaData(), Column("id", Integer), Column("payload", LargeBinary))
    values = [b"\x00\x01GaussDB\xff\x10", b"", b"deadbeef", bytes(range(256)), None]
    try:
        table.create(engine)
        with engine.begin() as conn:
            conn.execute(table.insert(), [{"id": i, "payload": v} for i, v in enumerate(values)])
        with engine.connect() as conn:
            actual = conn.execute(select(table.c.payload).order_by(table.c.id)).scalars().all()
        assert actual == values
        assert all(v is None or isinstance(v, bytes) for v in actual)
    finally:
        _drop_table(engine, name)


@pytest.mark.integration
def test_live_unique_constraint_catalog_arrays(engine):
    name = _table_name("gdb_sa_live_unique_arrays")
    # Put code first so the default distribution key is included in both
    # constraints, avoiding a requirement for global secondary indexes.
    table = Table(name, MetaData(), Column("code", Integer, nullable=False),
                  Column("id", Integer, nullable=False),
                  UniqueConstraint("code", name=name + "_single"),
                  UniqueConstraint("id", "code", name=name + "_multi"))
    try:
        table.create(engine)
        with engine.begin() as conn:
            conn.execute(table.insert(), {"id": 1, "code": 10})
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(table.insert(), {"id": 2, "code": 10})
        inspector = inspect(engine)
        expected = {name + "_single": ["code"], name + "_multi": ["id", "code"]}
        constraints = {c["name"]: c["column_names"] for c in inspector.get_unique_constraints(name)}
        assert constraints == expected
        # Both Inspector entry points must use the logical constraint columns,
        # even if a distributed backing index appends hidden system attributes.
        inspector.clear_cache()
        multi_constraints = inspector.get_multi_unique_constraints(filter_names=[name])
        assert {c["name"]: c["column_names"] for c in multi_constraints[(None, name)]} == expected
        indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes(name)}
        assert indexes == expected
        inspector.clear_cache()
        multi_indexes = inspector.get_multi_indexes(filter_names=[name])
        assert {i["name"]: i["column_names"] for i in multi_indexes[(None, name)]} == expected
    finally:
        _drop_table(engine, name)
