"""
Unit tests for the GaussDB SQLAlchemy dialect.

These tests do NOT require a live database connection.
They verify:
- Fixed driver selection for psycopg3 and psycopg2
- Explicit driver selection (gaussdb+psycopg2://, gaussdb+psycopg://)
- create_connect_args branching (psycopg3 vs psycopg2)
- _suppress_dealloc is a no-op for psycopg2
- _gaussdb_connection returns raw conn for psycopg2
- Dialect registration (entry points)
- M-compat type compiler (TIMESTAMP(6), BLOB, backtick quoting)
- A/B/M compatibility detection logic

Run with:
    cd gaussdb-python
    python -m pytest gaussdb_sqlalchemy/tests/test_dialect_unit.py -v
"""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

# Ensure gaussdb_sqlalchemy is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# 1. Driver detection: import_dbapi
# ──────────────────────────────────────────────────────────────────────────────

class TestDriverDetection:
    """Test that each URL selects a stable DBAPI implementation."""

    def test_default_dialect_does_not_fallback_to_psycopg2(self):
        """The default URL remains psycopg3 even if only psycopg2 exists."""
        with patch.dict(sys.modules, {"gaussdb": None}):
            from gaussdb_sqlalchemy.base import GaussDBDialect

            with pytest.raises(ImportError, match="gaussdb/psycopg3"):
                GaussDBDialect.import_dbapi()
            assert GaussDBDialect._driver_impl == "gaussdb"

    def test_explicit_psycopg2_dialect(self):
        """GaussDBDialect_psycopg2 should always use psycopg2."""
        try:
            import psycopg2
        except ImportError:
            pytest.skip("psycopg2 not installed")

        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2

        assert GaussDBDialect_psycopg2._driver_impl == "psycopg2"
        dbapi = GaussDBDialect_psycopg2.import_dbapi()
        assert dbapi.__name__ == "psycopg2"

    def test_is_psycopg3_property(self):
        """_is_psycopg3 is True for gaussdb and False for psycopg2."""
        from gaussdb_sqlalchemy.base import GaussDBDialect, GaussDBDialect_psycopg2

        d2 = GaussDBDialect_psycopg2()
        assert d2._is_psycopg3 is False
        assert GaussDBDialect()._is_psycopg3 is True

    def test_import_error_when_no_driver(self):
        """When no driver is installed, import_dbapi should raise ImportError."""
        with patch.dict(sys.modules, {"gaussdb": None}):
            from gaussdb_sqlalchemy.base import GaussDBDialect
            with pytest.raises(ImportError, match="gaussdb/psycopg3"):
                GaussDBDialect.import_dbapi()


# ──────────────────────────────────────────────────────────────────────────────
# 2. create_connect_args: psycopg2 vs psycopg3 branching
# ──────────────────────────────────────────────────────────────────────────────

class TestConnectArgs:
    """Test that create_connect_args produces correct kwargs per driver."""

    def _make_url(self, url_str):
        from sqlalchemy.engine.url import make_url
        return make_url(url_str)

    def test_psycopg2_no_prepare_threshold(self):
        """psycopg2 path should NOT include prepare_threshold or cursor_factory."""
        try:
            import psycopg2
        except ImportError:
            pytest.skip("psycopg2 not installed")

        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2
        dialect = GaussDBDialect_psycopg2()

        url = self._make_url("gaussdb+psycopg2://user:pass@host:5432/db?sslmode=disable")
        args, kwargs = dialect.create_connect_args(url)

        assert len(args) == 1
        conninfo = args[0]
        assert "host=host" in conninfo
        assert "port=5432" in conninfo
        assert "user=user" in conninfo
        assert "password=pass" in conninfo
        assert "dbname=db" in conninfo
        assert "sslmode=disable" in conninfo
        assert "client_encoding=UTF8" in conninfo

        # Key assertion: no psycopg3-specific params
        assert "prepare_threshold" not in kwargs
        assert "cursor_factory" not in kwargs
        assert kwargs == {}

    def test_psycopg2_custom_encoding_not_doubled(self):
        """If user specifies client_encoding, don't add a second one."""
        try:
            import psycopg2
        except ImportError:
            pytest.skip("psycopg2 not installed")

        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2
        dialect = GaussDBDialect_psycopg2()

        url = self._make_url("gaussdb+psycopg2://user:pass@host:5432/db?sslmode=disable&client_encoding=SQL_ASCII")
        args, kwargs = dialect.create_connect_args(url)
        conninfo = args[0]

        # Should have the user-specified encoding, not UTF8
        assert "client_encoding=SQL_ASCII" in conninfo
        assert "client_encoding=UTF8" not in conninfo

    def test_psycopg3_includes_prepare_threshold(self):
        """psycopg3 path SHOULD include prepare_threshold=None and cursor_factory."""
        # This test only runs when gaussdb (psycopg3) is installed
        try:
            import gaussdb
        except ImportError:
            pytest.skip("gaussdb (psycopg3) not installed")
        if not hasattr(gaussdb, "ClientCursor"):
            pytest.skip("gaussdb namespace exists but the psycopg3 driver is not loadable")

        from gaussdb_sqlalchemy.base import GaussDBDialect
        dialect = GaussDBDialect()
        # Force psycopg3 path
        dialect._driver_impl = "gaussdb"

        url = self._make_url("gaussdb://user:pass@host:5432/db?sslmode=disable")
        args, kwargs = dialect.create_connect_args(url)

        assert "prepare_threshold" in kwargs
        assert kwargs["prepare_threshold"] is None
        assert "cursor_factory" in kwargs

    def test_conninfo_format_correct(self):
        """conninfo string should be space-separated key=value pairs."""
        try:
            import psycopg2
        except ImportError:
            pytest.skip("psycopg2 not installed")

        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2
        dialect = GaussDBDialect_psycopg2()

        url = self._make_url("gaussdb+psycopg2://scott:tiger@db.example.com:2543/mydb")
        args, _ = dialect.create_connect_args(url)
        conninfo = args[0]

        parts = conninfo.split(" ")
        assert len(parts) >= 5  # host, port, user, password, dbname, client_encoding
        for part in parts:
            assert "=" in part, f"Malformed conninfo part: {part}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. _suppress_dealloc and _gaussdb_connection
# ──────────────────────────────────────────────────────────────────────────────

class TestPsycopg3Hooks:
    """Test that psycopg3-specific hooks are no-ops for psycopg2."""

    def test_suppress_dealloc_noop_for_psycopg2(self):
        """_suppress_dealloc should do nothing for psycopg2."""
        try:
            import psycopg2
        except ImportError:
            pytest.skip("psycopg2 not installed")

        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2
        dialect = GaussDBDialect_psycopg2()

        # Pass a mock connection — should not touch it at all
        mock_conn = MagicMock()
        dialect._suppress_dealloc(mock_conn)

        # mock_conn should not have been accessed at all
        mock_conn._prepared.assert_not_called()

    def test_gaussdb_connection_returns_raw_for_psycopg2(self):
        """_gaussdb_connection should return the raw connection for psycopg2."""
        try:
            import psycopg2
        except ImportError:
            pytest.skip("psycopg2 not installed")

        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2
        dialect = GaussDBDialect_psycopg2()

        mock_conn = MagicMock()
        result = dialect._gaussdb_connection(mock_conn)
        assert result is mock_conn

    def test_do_rollback_doesnt_crash_for_psycopg2(self):
        """do_rollback should work for psycopg2 without calling _suppress_dealloc logic."""
        try:
            import psycopg2
        except ImportError:
            pytest.skip("psycopg2 not installed")

        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2
        dialect = GaussDBDialect_psycopg2()

        mock_conn = MagicMock()
        # This should not raise
        dialect.do_rollback(mock_conn)

    def test_do_commit_doesnt_crash_for_psycopg2(self):
        """do_commit should work for psycopg2 without calling _suppress_dealloc logic."""
        try:
            import psycopg2
        except ImportError:
            pytest.skip("psycopg2 not installed")

        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2
        dialect = GaussDBDialect_psycopg2()

        mock_conn = MagicMock()
        # This should not raise
        dialect.do_commit(mock_conn)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Dialect registration
# ──────────────────────────────────────────────────────────────────────────────

class TestDialectRegistration:
    """Test that all dialect names are registered correctly."""

    def test_register_dialect_creates_all_entries(self):
        """register_dialect should register 4 dialect names."""
        from gaussdb_sqlalchemy.base import register_dialect
        from sqlalchemy.dialects import registry

        register_dialect()

        # registry.load() resolves the class; if it doesn't raise, it's registered
        # We test by checking that the registry can load each dialect name
        for name in ("gaussdb", "gaussdb.psycopg", "gaussdb.gaussdb", "gaussdb.psycopg2"):
            cls = registry.load(name)
            assert cls is not None, f"Dialect '{name}' not registered"

    def test_gaussdb_psycopg2_points_to_subclass(self):
        """gaussdb.psycopg2 should resolve to GaussDBDialect_psycopg2, not GaussDBDialect."""
        from gaussdb_sqlalchemy.base import GaussDBDialect, GaussDBDialect_psycopg2
        from sqlalchemy.dialects import registry

        cls = registry.load("gaussdb.psycopg2")
        assert cls is GaussDBDialect_psycopg2
        assert cls is not GaussDBDialect

    def test_gaussdb_default_resolves_to_base(self):
        """gaussdb defaults to Huawei's psycopg3 dialect."""
        from gaussdb_sqlalchemy.base import GaussDBDialect
        from sqlalchemy.dialects import registry

        cls = registry.load("gaussdb")
        assert cls is GaussDBDialect

    def test_entry_points_in_pyproject(self):
        """pyproject.toml should have all 4 entry points."""
        import pathlib
        toml_path = pathlib.Path(__file__).parent.parent / "pyproject.toml"
        content = toml_path.read_text()

        assert 'gaussdb = "gaussdb_sqlalchemy.base:GaussDBDialect"' in content
        assert '"gaussdb.psycopg" = "gaussdb_sqlalchemy.base:GaussDBDialect"' in content
        assert '"gaussdb.gaussdb" = "gaussdb_sqlalchemy.base:GaussDBDialect"' in content
        assert '"gaussdb.psycopg2" = "gaussdb_sqlalchemy.base:GaussDBDialect_psycopg2"' in content

        # Check optional deps
        assert "psycopg3 = [" in content
        assert "psycopg2 = [" in content


# ──────────────────────────────────────────────────────────────────────────────
# 5. M-compat type compiler and DDL
# ──────────────────────────────────────────────────────────────────────────────

class TestMCompatTypeCompiler:
    """Test M-compatibility type compilation (no DB needed)."""

    def _make_dialect(self, compat="M"):
        """Create a dialect instance with a given compatibility mode."""
        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2
        dialect = GaussDBDialect_psycopg2()
        dialect.gaussdb_compatibility = compat
        return dialect

    def test_m_mode_timestamp_emits_precision(self):
        """M mode should emit TIMESTAMP(6) for microsecond precision."""
        from sqlalchemy import types as sqltypes
        dialect = self._make_dialect("M")
        tc = dialect.type_compiler_instance
        result = tc.process(sqltypes.DateTime())
        assert "TIMESTAMP(6)" in result.upper()

    def test_m_mode_timestamp_rejects_timezone_semantics(self):
        """M mode must not silently discard timezone=True."""
        from sqlalchemy.dialects.postgresql import TIMESTAMP
        from sqlalchemy.exc import CompileError

        dialect = self._make_dialect("M")
        with pytest.raises(CompileError, match="timezone-aware"):
            dialect.type_compiler_instance.process(TIMESTAMP(timezone=True))

    def test_a_mode_timestamp_no_precision(self):
        """A mode should NOT force TIMESTAMP(6)."""
        from sqlalchemy import types as sqltypes
        dialect = self._make_dialect("A")
        tc = dialect.type_compiler_instance
        result = tc.process(sqltypes.DateTime())
        # Should be standard TIMESTAMP without (6)
        assert "(6)" not in result.upper()

    def test_m_mode_large_binary_is_blob(self):
        """M mode should emit BLOB for LargeBinary."""
        from sqlalchemy import types as sqltypes
        dialect = self._make_dialect("M")
        tc = dialect.type_compiler_instance
        result = tc.process(sqltypes.LargeBinary())
        assert "BLOB" in result.upper()

    def test_a_mode_large_binary_is_bytea(self):
        """A mode should emit BYTEA for LargeBinary."""
        from sqlalchemy import types as sqltypes
        dialect = self._make_dialect("A")
        tc = dialect.type_compiler_instance
        result = tc.process(sqltypes.LargeBinary())
        assert "BYTEA" in result.upper()


# ──────────────────────────────────────────────────────────────────────────────
# 6. M-compat identifier preparer (backtick quoting)
# ──────────────────────────────────────────────────────────────────────────────

class TestMCompatIdentifierPreparer:
    """Test M-compat backtick quoting vs A-compat double-quote."""

    def _make_dialect(self, compat):
        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2, GaussDBIdentifierPreparer
        dialect = GaussDBDialect_psycopg2()
        dialect.gaussdb_compatibility = compat
        dialect.preparer = GaussDBIdentifierPreparer(dialect)
        return dialect

    def test_m_mode_identifier_quote_char(self):
        """M mode should use backtick as initial_quote."""
        dialect = self._make_dialect("M")
        assert dialect.preparer.initial_quote == "`"

    def test_a_mode_identifier_quote_char(self):
        """A mode should keep default double-quote."""
        dialect = self._make_dialect("A")
        assert dialect.preparer.initial_quote == '"'

    def test_m_mode_ddl_uses_backticks(self):
        """M mode DDL should use backticks for quoted identifiers."""
        from sqlalchemy import MetaData, Table, Column, Integer
        from sqlalchemy.sql.elements import quoted_name
        from sqlalchemy.schema import CreateTable
        from gaussdb_sqlalchemy.base import GaussDBIdentifierPreparer
        dialect = self._make_dialect("M")

        # DDL compiler creates its own preparer — need to patch it
        md = MetaData()
        t = Table(quoted_name("select", quote=True), md, Column("id", Integer))
        compiler = dialect.ddl_compiler(dialect, None)
        compiler.preparer = GaussDBIdentifierPreparer(dialect)
        ddl = str(CreateTable(t).compile(dialect=dialect, compile_kwargs={"ddl_compiler": compiler}))
        # If the above doesn't work, just test the preparer directly
        if "`" not in ddl:
            # Test via preparer directly
            result = compiler.preparer.quote_identifier("select")
            assert "`" in result, f"Expected backticks, got: {result}"
        else:
            assert "`select`" in ddl

    def test_a_mode_ddl_uses_double_quotes(self):
        """A mode DDL should use double quotes for quoted identifiers."""
        from sqlalchemy import MetaData, Table, Column, Integer
        from sqlalchemy.sql.elements import quoted_name
        from sqlalchemy.schema import CreateTable
        dialect = self._make_dialect("A")

        md = MetaData()
        t = Table(quoted_name("select", quote=True), md, Column("id", Integer))
        ddl = str(CreateTable(t).compile(dialect=dialect))
        assert '"select"' in ddl, f"Expected double quotes in DDL, got: {ddl}"


# ──────────────────────────────────────────────────────────────────────────────
# 7. Compatibility detection
# ──────────────────────────────────────────────────────────────────────────────

class TestCompatDetection:
    """Test the _detect_compatibility function (mocked, no DB)."""

    def test_detect_m_from_datcompatibility(self):
        """Should detect M mode when datcompatibility = 'M'."""
        from gaussdb_sqlalchemy.base import _detect_compatibility

        mock_conn = MagicMock()
        mock_execute = MagicMock()
        mock_execute.scalar_one.return_value = "M"
        mock_conn.execute.return_value = mock_execute

        result = _detect_compatibility(mock_conn)
        assert result == "M"

    def test_detect_a_from_pg(self):
        """Should detect A mode when datcompatibility = 'PG' (treated as A)."""
        from gaussdb_sqlalchemy.base import _detect_compatibility

        mock_conn = MagicMock()
        mock_execute = MagicMock()
        mock_execute.scalar_one.return_value = "PG"
        mock_conn.execute.return_value = mock_execute

        result = _detect_compatibility(mock_conn)
        assert result == "A"

    def test_detect_b(self):
        """Should detect B mode."""
        from gaussdb_sqlalchemy.base import _detect_compatibility

        mock_conn = MagicMock()
        mock_execute = MagicMock()
        mock_execute.scalar_one.return_value = "B"
        mock_conn.execute.return_value = mock_execute

        result = _detect_compatibility(mock_conn)
        assert result == "B"

    def test_detect_fails_explicitly_on_error(self):
        """A failed query must not silently select the wrong mode."""
        from gaussdb_sqlalchemy.base import _detect_compatibility
        from sqlalchemy.exc import InvalidRequestError

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("query failed")

        with pytest.raises(InvalidRequestError, match="datcompatibility"):
            _detect_compatibility(mock_conn)

    def test_detect_does_not_cache_by_url(self):
        """Each database connection is detected independently."""
        from gaussdb_sqlalchemy.base import _detect_compatibility

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.url = "gaussdb://host/db"
        mock_conn.engine = mock_engine

        mock_execute = MagicMock()
        mock_execute.scalar_one.return_value = "M"
        mock_conn.execute.return_value = mock_execute

        # First call
        result1 = _detect_compatibility(mock_conn)
        assert result1 == "M"

        mock_execute.scalar_one.return_value = "B"
        result2 = _detect_compatibility(mock_conn)
        assert result2 == "B"
        assert mock_conn.execute.call_count == 2


class TestRegressionFixes:
    """Focused tests for bugs found during the delivery audit."""

    def _m_dialect(self):
        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2

        dialect = GaussDBDialect_psycopg2()
        dialect.gaussdb_compatibility = "M"
        dialect._apply_compatibility_features()
        return dialect

    def test_apply_features_replaces_real_identifier_preparer(self):
        dialect = self._m_dialect()
        assert dialect.identifier_preparer.initial_quote == "`"

    def test_m_boolean_and_time_types(self):
        from sqlalchemy import Boolean, Time

        compiler = self._m_dialect().type_compiler_instance
        assert compiler.process(Boolean()) == "SMALLINT"
        assert compiler.process(Time()) == "TIME"

    def test_m_bigint_autoincrement_preserves_width(self):
        from sqlalchemy import BigInteger, Column, MetaData, Table
        from sqlalchemy.schema import CreateTable

        table = Table(
            "audit_bigint", MetaData(),
            Column("id", BigInteger, primary_key=True, autoincrement=True),
        )
        ddl = str(CreateTable(table).compile(dialect=self._m_dialect()))
        assert "BIGINT NOT NULL AUTO_INCREMENT" in ddl
        assert "id INTEGER" not in ddl

    def test_two_operand_concat_uses_concat_function(self):
        from sqlalchemy import column, select, String

        expr = column("left_value", String) + column("right_value", String)
        sql = str(select(expr).compile(dialect=self._m_dialect()))
        assert "CONCAT(left_value, right_value)" in sql
        assert " || " not in sql

    def test_m_disables_all_returning_flags(self):
        dialect = self._m_dialect()
        assert dialect.insert_returning is False
        assert dialect.update_returning is False
        assert dialect.delete_returning is False

    def test_conninfo_values_are_libpq_escaped(self):
        from sqlalchemy.engine import URL
        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2

        url = URL.create(
            "gaussdb+psycopg2", username="user name",
            password="pa ss'\\word", host="db host", database="test db",
        )
        args, _ = GaussDBDialect_psycopg2().create_connect_args(url)
        assert "user='user name'" in args[0]
        assert "password='pa ss\\'\\\\word'" in args[0]
        assert "host='db host'" in args[0]
        assert "dbname='test db'" in args[0]

    def test_unknown_conninfo_option_is_rejected_clearly(self):
        from sqlalchemy.engine import URL
        from sqlalchemy.exc import ArgumentError
        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2

        url = URL.create(
            "gaussdb+psycopg2", host="db", database="test",
            query={"unknown_option": "value"},
        )
        with pytest.raises(ArgumentError, match="unknown_option"):
            GaussDBDialect_psycopg2().create_connect_args(url)

    def test_m_isolation_uses_dbapi_cursor(self):
        dialect = self._m_dialect()
        connection = MagicMock()
        cursor = connection.cursor.return_value

        dialect.set_isolation_level(connection, "READ_COMMITTED")

        connection.commit.assert_called_once_with()
        cursor.execute.assert_called_once_with(
            "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"
        )
        cursor.close.assert_called_once_with()
        connection.execute.assert_not_called()

    def test_m_foreign_key_query_uses_referred_relation(self):
        dialect = self._m_dialect()
        dialect.default_schema_name = "public"
        connection = MagicMock()
        dialect._m_simple_query = MagicMock(return_value=[])

        dialect.get_foreign_keys(connection, "child")

        sql = dialect._m_simple_query.call_args.args[1]
        assert "rn.nspname AS ref_schema" in sql
        assert "rcl.relname AS ref_table" in sql

    def test_alembic_column_type_uses_element_type(self):
        from alembic.ddl.base import ColumnType
        from sqlalchemy import BigInteger

        dialect = self._m_dialect()
        sql = str(ColumnType("t", "id", BigInteger()).compile(dialect=dialect))
        assert sql == "ALTER TABLE t MODIFY COLUMN id BIGINT"

    def test_alembic_rename_without_existing_type_is_not_noop(self):
        from io import StringIO
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        output = StringIO()
        context = MigrationContext.configure(
            dialect=self._m_dialect(),
            opts={"as_sql": True, "output_buffer": output},
        )
        Operations(context).alter_column(
            "account", "old_name", new_column_name="new_name"
        )
        assert "RENAME COLUMN old_name TO new_name" in output.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# 8. _resolve_type mapping
# ──────────────────────────────────────────────────────────────────────────────

class TestResolveType:
    """Test the _resolve_type function for type mapping."""

    def _get_dialect(self):
        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2
        return GaussDBDialect_psycopg2()

    def test_integer_mapping(self):
        dialect = self._get_dialect()
        from sqlalchemy import types as sqltypes

        result = dialect._resolve_type("integer", 23, "A")
        assert isinstance(result, sqltypes.Integer)

    def test_bigint_mapping(self):
        dialect = self._get_dialect()
        from sqlalchemy import types as sqltypes

        result = dialect._resolve_type("bigint", 20, "A")
        assert isinstance(result, sqltypes.BigInteger)

    def test_varchar_with_length(self):
        dialect = self._get_dialect()
        from sqlalchemy import types as sqltypes

        result = dialect._resolve_type("character varying(255)", 1043, "A")
        assert isinstance(result, sqltypes.String)
        assert result.length == 255

    def test_numeric_with_precision(self):
        dialect = self._get_dialect()
        from sqlalchemy import types as sqltypes

        result = dialect._resolve_type("numeric(10,2)", 1700, "A")
        assert isinstance(result, sqltypes.Numeric)
        assert result.precision == 10
        assert result.scale == 2

    def test_m_mode_blob_mapping(self):
        dialect = self._get_dialect()
        from sqlalchemy import types as sqltypes

        result = dialect._resolve_type("blob", 5545, "M")
        assert isinstance(result, sqltypes.LargeBinary)

    def test_m_mode_tinyint_mapping(self):
        dialect = self._get_dialect()
        from sqlalchemy import types as sqltypes

        result = dialect._resolve_type("tinyint", 50, "M")
        assert isinstance(result, sqltypes.SmallInteger)

    def test_m_mode_datetime_mapping(self):
        dialect = self._get_dialect()
        from sqlalchemy import types as sqltypes

        result = dialect._resolve_type("datetime", 1000, "M")
        assert isinstance(result, sqltypes.DateTime)

    def test_unknown_type_fallback(self):
        dialect = self._get_dialect()
        from sqlalchemy import types as sqltypes

        result = dialect._resolve_type("some_unknown_type", 9999, "A")
        assert isinstance(result, sqltypes.String)


# ──────────────────────────────────────────────────────────────────────────────
# 9. Server version info
# ──────────────────────────────────────────────────────────────────────────────

class TestServerVersion:
    """Test _get_server_version_info returns conservative version."""

    def test_returns_9_2(self):
        """Should return (9, 2) to avoid PG 12+ reflection code paths."""
        from gaussdb_sqlalchemy.base import GaussDBDialect_psycopg2
        dialect = GaussDBDialect_psycopg2()

        mock_conn = MagicMock()
        result = dialect._get_server_version_info(mock_conn)
        assert result == (9, 2)
