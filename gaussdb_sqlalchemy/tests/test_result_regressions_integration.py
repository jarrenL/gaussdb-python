"""Live regressions for native JSON, binary data, and catalog arrays.

Uses the same URL matrix and cleanup rules as the basic 26 live cases.
"""
import json

import pytest
from sqlalchemy import (
    Column, Integer, JSON, LargeBinary, MetaData, Table, UniqueConstraint,
    create_engine, inspect, select,
)
from sqlalchemy.exc import IntegrityError

from .test_dialect_integration import engine, _table_name, _drop_table  # noqa: F401


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
        constraints = {c["name"]: c["column_names"] for c in inspect(engine).get_unique_constraints(name)}
        assert constraints[name + "_single"] == ["code"]
        assert constraints[name + "_multi"] == ["id", "code"]
    finally:
        _drop_table(engine, name)
