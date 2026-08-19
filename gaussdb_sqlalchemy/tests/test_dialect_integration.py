"""
Live GaussDB integration tests for the SQLAlchemy dialect.

These tests require a real GaussDB database and are skipped by default.
Configure one or more URLs with environment variables before running.

Examples:
    export GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL='gaussdb://user:pass@host:port/db?sslmode=disable'
    export GAUSSDB_SQLALCHEMY_PSYCOPG2_X86_URL='gaussdb+psycopg2://user:pass@host:port/db?sslmode=disable'
    python -m pytest gaussdb_sqlalchemy/tests/test_dialect_integration.py -v -rs
"""

from __future__ import annotations

import os
import platform
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import (
    Column,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, declarative_base


MATRIX_URL_ENV_KEYS = (
    "GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL",
    "GAUSSDB_SQLALCHEMY_PSYCOPG3_ARM_URL",
    "GAUSSDB_SQLALCHEMY_PSYCOPG2_X86_URL",
    "GAUSSDB_SQLALCHEMY_PSYCOPG2_ARM_URL",
)

LEGACY_URL_ENV_KEYS = (
    "GAUSSDB_SQLALCHEMY_TEST_URL",
    "GAUSSDB_SQLALCHEMY_PSYCOPG3_URL",
    "GAUSSDB_SQLALCHEMY_PSYCOPG2_URL",
    "GAUSSDB_SQLALCHEMY_TEST_URL_A",
    "GAUSSDB_SQLALCHEMY_TEST_URL_B",
    "GAUSSDB_SQLALCHEMY_TEST_URL_M",
)


def _configured_urls() -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    seen: set[str] = set()

    for key in MATRIX_URL_ENV_KEYS + LEGACY_URL_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value and value not in seen:
            seen.add(value)
            cases.append((key, value))

    for index, value in enumerate(_split_urls(os.environ.get("GAUSSDB_SQLALCHEMY_TEST_URLS", "")), start=1):
        if value not in seen:
            seen.add(value)
            cases.append((f"GAUSSDB_SQLALCHEMY_TEST_URLS[{index}]", value))

    return cases


def _split_urls(value: str) -> list[str]:
    if not value.strip():
        return []
    # Prefer newlines for URLs because passwords and query strings may contain
    # punctuation. Semicolons are also accepted for simple internal scripts.
    parts = []
    for line in value.replace(";", "\n").splitlines():
        item = line.strip()
        if item:
            parts.append(item)
    return parts


URL_CASES = _configured_urls() or [("not-configured", "")]


def _driver_from_url(url: str) -> str:
    return "psycopg2" if url.startswith("gaussdb+psycopg2://") else "psycopg3"


def _current_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine or "unknown"


def _expected_arch_from_label(label: str) -> str | None:
    if label.endswith("_X86_URL"):
        return "x86_64"
    if label.endswith("_ARM_URL"):
        return "arm64"
    return None


def _case_id(case: tuple[str, str]) -> str:
    label, url = case
    if not url:
        return label
    arch = _expected_arch_from_label(label) or _current_arch()
    return f"{label}:{_driver_from_url(url)}:{arch}"


def _require_driver(url: str) -> None:
    if url.startswith("gaussdb+psycopg2://"):
        pytest.importorskip("psycopg2")
    else:
        pytest.importorskip("gaussdb")


@pytest.fixture(params=URL_CASES, ids=_case_id)
def engine(request):
    label, url = request.param
    if not url:
        pytest.skip(
            "Set GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL, "
            "GAUSSDB_SQLALCHEMY_PSYCOPG3_ARM_URL, "
            "GAUSSDB_SQLALCHEMY_PSYCOPG2_X86_URL, "
            "GAUSSDB_SQLALCHEMY_PSYCOPG2_ARM_URL, or a legacy "
            "GAUSSDB_SQLALCHEMY_*URL variable to run live tests."
        )

    expected_arch = _expected_arch_from_label(label)
    if expected_arch and expected_arch != _current_arch():
        pytest.skip(f"{label} is for {expected_arch}, current machine is {_current_arch()}.")

    _require_driver(url)

    from gaussdb_sqlalchemy.base import register_dialect

    register_dialect()
    eng = create_engine(url, future=True, pool_pre_ping=True)
    eng._gaussdb_test_label = label
    eng._gaussdb_test_driver = _driver_from_url(url)
    eng._gaussdb_test_arch = _current_arch()
    try:
        with eng.connect() as conn:
            assert conn.execute(text("select 1")).scalar_one() == 1
        yield eng
    finally:
        eng.dispose()


def _table_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _drop_table(engine, table_name: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


@pytest.mark.integration
def test_runtime_driver_and_architecture(engine):
    driver = engine._gaussdb_test_driver
    arch = engine._gaussdb_test_arch

    assert driver in {"psycopg2", "psycopg3"}
    assert arch in {"x86_64", "arm64"}
    assert sys.version_info >= (3, 7)

    if driver == "psycopg2":
        import psycopg2

        assert getattr(psycopg2, "__version__", "")
    else:
        import gaussdb

        assert getattr(gaussdb, "__version__", "")


@pytest.mark.integration
def test_live_select_and_compatibility_detection(engine):
    with engine.connect() as conn:
        assert conn.execute(text("select 1")).scalar_one() == 1
        compat = conn.execute(
            text(
                "select datcompatibility from pg_database "
                "where datname = current_database()"
            )
        ).scalar_one()

    assert str(compat).strip().upper()[:1] in {"A", "B", "M", "P"}
    assert engine.dialect.gaussdb_compatibility in {"A", "B", "M"}


@pytest.mark.integration
def test_bound_parameters_and_scalar_results(engine):
    with engine.connect() as conn:
        row = conn.execute(
            text("select :number as number_value, :message as message_value"),
            {"number": 42, "message": "GaussDB 参数绑定"},
        ).one()

    assert row.number_value == 42
    assert row.message_value == "GaussDB 参数绑定"


@pytest.mark.integration
def test_core_create_insert_query_reflect_drop(engine):
    table_name = _table_name("gdb_sa_live_core")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("name", String(64), nullable=False),
        Column("amount", Numeric(12, 2)),
        Column("created_at", DateTime),
    )

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        inspector = inspect(engine)
        assert inspector.has_table(table_name)

        with engine.begin() as conn:
            conn.execute(
                table.insert(),
                [
                    {"id": 1, "name": "alpha", "amount": Decimal("12.30")},
                    {"id": 2, "name": "beta", "amount": Decimal("45.60")},
                ],
            )
            rows = conn.execute(
                select(table.c.id, table.c.name)
                .where(table.c.amount > Decimal("20"))
                .order_by(table.c.id)
            ).all()
            assert rows == [(2, "beta")]

        columns = {col["name"]: col for col in inspect(engine).get_columns(table_name)}
        assert {"id", "name", "amount", "created_at"}.issubset(columns)
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_transaction_rollback(engine):
    table_name = _table_name("gdb_sa_live_tx")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("name", String(64), nullable=False),
    )

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        with engine.connect() as conn:
            trans = conn.begin()
            conn.execute(table.insert(), {"id": 1, "name": "will_rollback"})
            trans.rollback()

            count = conn.execute(select(table.c.id)).all()
            assert count == []
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_transaction_commit_persists_data(engine):
    table_name = _table_name("gdb_sa_live_commit")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("value", String(64), nullable=False),
    )

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(table.insert(), {"id": 1, "value": "committed"})

        with engine.connect() as conn:
            assert conn.execute(select(table.c.value)).scalar_one() == "committed"
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_savepoint_rollback_keeps_outer_transaction(engine):
    table_name = _table_name("gdb_sa_live_savepoint")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("value", String(64), nullable=False),
    )

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(table.insert(), {"id": 1, "value": "outer"})
            nested = conn.begin_nested()
            conn.execute(table.insert(), {"id": 2, "value": "savepoint"})
            nested.rollback()
            conn.execute(table.insert(), {"id": 3, "value": "after_savepoint"})

        with engine.connect() as conn:
            ids = conn.execute(select(table.c.id).order_by(table.c.id)).scalars().all()
        assert ids == [1, 3]
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_unicode_null_empty_and_long_text_round_trip(engine):
    table_name = _table_name("gdb_sa_live_text")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("short_text", String(128)),
        Column("long_text", Text),
    )
    long_value = "高斯数据库-" * 400

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(
                table.insert(),
                [
                    {"id": 1, "short_text": "中文🙂", "long_text": long_value},
                    {"id": 2, "short_text": "", "long_text": None},
                ],
            )

        with engine.connect() as conn:
            rows = conn.execute(select(table).order_by(table.c.id)).mappings().all()
        assert rows[0]["short_text"] == "中文🙂"
        assert rows[0]["long_text"] == long_value
        assert rows[1]["short_text"] == ""
        assert rows[1]["long_text"] is None
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_numeric_boolean_date_datetime_round_trip(engine):
    table_name = _table_name("gdb_sa_live_types")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("amount", Numeric(12, 3), nullable=False),
        Column("enabled", Boolean, nullable=False),
        Column("business_date", Date, nullable=False),
        Column("created_at", DateTime, nullable=False),
    )
    expected_datetime = datetime(2026, 8, 19, 10, 11, 12, 123000)

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(
                table.insert(),
                {
                    "id": 1,
                    "amount": Decimal("12345.678"),
                    "enabled": True,
                    "business_date": date(2026, 8, 19),
                    "created_at": expected_datetime,
                },
            )

        with engine.connect() as conn:
            row = conn.execute(select(table)).mappings().one()
        assert row["amount"] == Decimal("12345.678")
        assert bool(row["enabled"]) is True
        assert row["business_date"] == date(2026, 8, 19)
        assert row["created_at"] == expected_datetime
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_binary_round_trip(engine):
    table_name = _table_name("gdb_sa_live_binary")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("payload", LargeBinary, nullable=False),
    )
    expected = b"\x00\x01GaussDB\xff\x10"

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(table.insert(), {"id": 1, "payload": expected})
        with engine.connect() as conn:
            actual = conn.execute(select(table.c.payload)).scalar_one()
        assert bytes(actual) == expected
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_executemany_update_and_delete(engine):
    table_name = _table_name("gdb_sa_live_batch")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("value", Integer, nullable=False),
    )

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(
                table.insert(),
                [{"id": index, "value": index * 10} for index in range(1, 6)],
            )
            conn.execute(table.update().where(table.c.id >= 3).values(value=99))
            conn.execute(table.delete().where(table.c.id == 1))

        with engine.connect() as conn:
            rows = conn.execute(
                select(table.c.id, table.c.value).order_by(table.c.id)
            ).all()
        assert rows == [(2, 20), (3, 99), (4, 99), (5, 99)]
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_primary_key_and_column_reflection(engine):
    table_name = _table_name("gdb_sa_live_pk")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("tenant_id", Integer, primary_key=True, autoincrement=False),
        Column("item_id", Integer, primary_key=True, autoincrement=False),
        Column("value", String(32), nullable=False),
    )

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        inspector = inspect(engine)
        pk = inspector.get_pk_constraint(table_name)
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert set(pk["constrained_columns"]) == {"tenant_id", "item_id"}
        assert columns["value"]["nullable"] is False
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_index_reflection(engine):
    table_name = _table_name("gdb_sa_live_index")
    index_name = f"{table_name}_name_idx"
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("name", String(64), nullable=False),
    )
    Index(index_name, table.c.name)

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        indexes = inspect(engine).get_indexes(table_name)
        reflected = next(index for index in indexes if index["name"] == index_name)
        assert reflected["column_names"] == ["name"]
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_unique_constraint_and_integrity_error(engine):
    table_name = _table_name("gdb_sa_live_unique")
    constraint_name = f"{table_name}_code_uq"
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=False),
        Column("code", String(32), nullable=False),
        UniqueConstraint("code", name=constraint_name),
    )

    _drop_table(engine, table_name)
    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(table.insert(), {"id": 1, "code": "same"})

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(table.insert(), {"id": 2, "code": "same"})

        constraints = inspect(engine).get_unique_constraints(table_name)
        assert any(set(item["column_names"]) == {"code"} for item in constraints)
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_statement_error_then_connection_rollback_and_reuse(engine):
    with engine.connect() as conn:
        with pytest.raises(Exception):
            conn.execute(text("select * from gdb_sa_table_that_does_not_exist"))
        conn.rollback()
        assert conn.execute(text("select 1")).scalar_one() == 1


@pytest.mark.integration
def test_connection_pool_repeated_checkouts(engine):
    for expected in range(1, 4):
        with engine.connect() as conn:
            assert conn.execute(
                text("select :value"), {"value": expected}
            ).scalar_one() == expected


@pytest.mark.integration
def test_orm_crud(engine):
    table_name = _table_name("gdb_sa_live_orm")
    Base = declarative_base()

    class LiveItem(Base):
        __tablename__ = table_name

        id = Column(Integer, primary_key=True, autoincrement=False)
        name = Column(String(64), nullable=False)

    _drop_table(engine, table_name)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(LiveItem(id=1, name="created"))
            session.commit()

        with Session(engine) as session:
            item = session.get(LiveItem, 1)
            assert item is not None
            assert item.name == "created"
            item.name = "updated"
            session.commit()

        with Session(engine) as session:
            assert session.get(LiveItem, 1).name == "updated"
            session.delete(session.get(LiveItem, 1))
            session.commit()
            assert session.get(LiveItem, 1) is None
    finally:
        _drop_table(engine, table_name)


@pytest.mark.integration
def test_orm_filter_order_count_and_limit(engine):
    table_name = _table_name("gdb_sa_live_orm_query")
    Base = declarative_base()

    class QueryItem(Base):
        __tablename__ = table_name

        id = Column(Integer, primary_key=True, autoincrement=False)
        category = Column(String(32), nullable=False)
        score = Column(Integer, nullable=False)

    _drop_table(engine, table_name)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add_all(
                [
                    QueryItem(id=1, category="A", score=10),
                    QueryItem(id=2, category="B", score=30),
                    QueryItem(id=3, category="A", score=20),
                    QueryItem(id=4, category="A", score=40),
                ]
            )
            session.commit()

        with Session(engine) as session:
            result = session.scalars(
                select(QueryItem)
                .where(QueryItem.category == "A")
                .order_by(QueryItem.score.desc())
                .limit(2)
            ).all()
            count = session.scalar(
                select(func.count()).select_from(QueryItem).where(QueryItem.category == "A")
            )
        assert [item.score for item in result] == [40, 20]
        assert count == 3
    finally:
        _drop_table(engine, table_name)
