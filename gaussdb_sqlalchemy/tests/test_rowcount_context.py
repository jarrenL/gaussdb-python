"""INSERT rowcount must survive a DBAPI cursor's automatic close.

These tests use real SQLAlchemy execution-context classes with a small fake
cursor; no database or importable native DBAPI is required.  In particular,
the count is the DBAPI's value, not an estimate from the input parameters.
"""

from unittest.mock import patch

import pytest
from sqlalchemy.dialects.postgresql.base import PGExecutionContext
from sqlalchemy.engine.interfaces import ExecuteStyle

from gaussdb_sqlalchemy import base


DIALECTS = [base.GaussDBDialect, base.GaussDBDialect_psycopg2]
MODES = ["A", "B", "M", "PG"]


class ClosingCursor:
    """Model psycopg3 resetting rowcount when its cursor is closed."""

    def __init__(self, rowcount=2):
        self._value = rowcount
        self.closed = False
        self.rowcount_reads = 0
        self.executed = []

    @property
    def rowcount(self):
        self.rowcount_reads += 1
        return -1 if self.closed else self._value

    def close(self):
        self.closed = True

    def execute(self, statement):
        self.executed.append(statement)
        # A subsequent SELECT must not replace the INSERT count either.
        self._value = 1

    def fetchone(self):
        return (42,)


@pytest.fixture(params=DIALECTS, ids=["psycopg3", "psycopg2"])
def dialect_cls(request):
    return request.param


@pytest.fixture(params=MODES)
def dialect(dialect_cls, request):
    instance = dialect_cls()
    instance.gaussdb_compatibility = request.param
    instance._apply_compatibility_features()
    return instance


@pytest.fixture
def context(dialect):
    instance = dialect.execution_ctx_cls.__new__(dialect.execution_ctx_cls)
    instance.dialect = dialect
    instance.cursor = ClosingCursor()
    instance.isinsert = True
    instance.isupdate = False
    instance.isdelete = False
    instance._is_explicit_returning = False
    instance._is_implicit_returning = False
    instance._rowcount = None
    instance.execute_style = ExecuteStyle.EXECUTEMANY
    instance.parameters = [{"id": i} for i in range(5)]
    return instance


def test_default_context_is_gaussdb_specific(dialect_cls):
    assert dialect_cls().execution_ctx_cls.__name__ == "GaussDBExecutionContext"


def test_compatibility_selects_rowcount_aware_context(dialect):
    expected = (
        "GaussDBMExecutionContext"
        if dialect.gaussdb_compatibility == "M"
        else "GaussDBExecutionContext"
    )
    assert dialect.execution_ctx_cls.__name__ == expected
    assert issubclass(dialect.execution_ctx_cls, PGExecutionContext)
    assert any(
        cls.__name__ == "GaussDBExecutionContext"
        for cls in dialect.execution_ctx_cls.__mro__
    )


@pytest.mark.parametrize("reported_count", [0, 2, -1])
@pytest.mark.parametrize(
    "execute_style", [ExecuteStyle.EXECUTE, ExecuteStyle.EXECUTEMANY]
)
def test_insert_rowcount_survives_cursor_close(
    context, reported_count, execute_style
):
    context.execute_style = execute_style
    context.cursor = ClosingCursor(reported_count)
    context.post_exec()

    # Preserve even an unknown count (-1); do not fabricate a success count.
    assert context._rowcount == reported_count
    assert context.cursor.rowcount_reads == 1
    context.cursor.close()
    assert context.cursor.rowcount == -1
    assert context.rowcount == reported_count


def test_insertmanyvalues_does_not_cache_a_single_page_count(context):
    context.execute_style = ExecuteStyle.INSERTMANYVALUES
    context.post_exec()
    assert context._rowcount is None
    assert context.cursor.rowcount_reads == 0


@pytest.mark.parametrize("preserved_count", [0, 7, -1])
def test_preexisting_rowcount_is_not_overwritten(context, preserved_count):
    context._rowcount = preserved_count
    context.post_exec()
    assert context._rowcount == preserved_count
    assert context.cursor.rowcount_reads == 0
    context.cursor.close()
    assert context.rowcount == preserved_count


@pytest.mark.parametrize(
    "returning_attribute", ["_is_explicit_returning", "_is_implicit_returning"]
)
def test_returning_does_not_cache_early(context, returning_attribute):
    setattr(context, returning_attribute, True)
    context.post_exec()
    assert context._rowcount is None
    assert context.cursor.rowcount_reads == 0


@pytest.mark.parametrize("operation", ["select", "update", "delete"])
def test_non_insert_keeps_sqlalchemy_rowcount_lifecycle(context, operation):
    context.isinsert = False
    context.isupdate = operation == "update"
    context.isdelete = operation == "delete"
    context.post_exec()
    assert context._rowcount is None
    assert context.cursor.rowcount_reads == 0


def test_post_exec_preserves_parent_hook(context):
    with patch.object(PGExecutionContext, "post_exec", autospec=True) as parent:
        context.post_exec()
    parent.assert_called_once_with(context)


def test_m_mode_still_obtains_last_insert_id(dialect_cls):
    dialect = dialect_cls()
    dialect.gaussdb_compatibility = "M"
    dialect._apply_compatibility_features()
    context = dialect.execution_ctx_cls.__new__(dialect.execution_ctx_cls)
    context.dialect = dialect
    context.cursor = ClosingCursor(2)
    context.isinsert = True
    context._is_explicit_returning = False
    context._is_implicit_returning = False
    context._rowcount = None
    context.execute_style = ExecuteStyle.EXECUTE

    context.post_exec()
    assert context.get_lastrowid() == 42
    assert context.cursor.executed == ["select last_insert_id()"]
    assert context._rowcount == 2
    context.cursor.close()
    assert context.rowcount == 2
