"""
SQLAlchemy dialect for GaussDB using the gaussdb (psycopg3 fork) DBAPI.

This dialect connects to GaussDB via the gaussdb Python package (a fork of
psycopg3 that uses libpq).  It auto-detects the database compatibility mode
(A/ORA=Oracle, B/MYSQL=legacy MySQL, M=MySQL M-Compatibility, PG=PostgreSQL)
and adapts SQL generation accordingly.
"""
from __future__ import annotations

import re

from sqlalchemy.dialects.postgresql.base import (
    PGDialect,
    PGDDLCompiler,
    PGTypeCompiler,
    PGIdentifierPreparer,
    PGExecutionContext,
    PGCompiler,
)
from sqlalchemy import types as sqltypes
from sqlalchemy import text
from sqlalchemy import exc as sa_exc
from sqlalchemy.sql import operators
from sqlalchemy.engine import reflection
from sqlalchemy.engine.interfaces import ExecuteStyle
from sqlalchemy.dialects.postgresql import BYTEA, JSON, JSONB

from .types import GaussDBBYTEA, GaussDBJSON, GaussDBJSONB, GaussDBLargeBinary

# ── compatibility detection ──────────────────────────────────────────────────

_COMPATIBILITY_NAMES = {
    "A": "A", "ORA": "A",
    "B": "B", "MYSQL": "B",
    "M": "M", "PG": "PG",
}

_LIBPQ_CONNINFO_OPTIONS = {
    "application_name", "channel_binding", "client_encoding",
    "connect_timeout", "dbname", "fallback_application_name", "gssencmode",
    "gsslib", "host", "hostaddr", "keepalives", "keepalives_count",
    "keepalives_idle", "keepalives_interval", "krbsrvname",
    "load_balance_hosts", "options", "passfile", "password", "port",
    "replication", "requirepeer", "requiressl", "service", "servicefile",
    "sslcert", "sslcompression", "sslcrl", "sslcrldir", "sslkey",
    "ssl_max_protocol_version", "ssl_min_protocol_version", "sslmode",
    "sslpassword", "sslrootcert", "sslsni", "target_session_attrs",
    "tcp_user_timeout", "user",
}


def _detect_compatibility(connection) -> str:
    """Normalize documented centralized/distributed catalog mode names.

    MYSQL means B, not M. PG retains its identity even though it shares
    the non-M SQL generation path. Unknown modes must not be guessed.
    """
    try:
        row = connection.execute(
            text(
                "select datcompatibility from pg_database "
                "where datname = current_database()"
            )
        ).scalar_one()
        if isinstance(row, (bytes, bytearray, memoryview)):
            row = bytes(row).decode("ascii")
        if not isinstance(row, str) or row.strip().upper() not in _COMPATIBILITY_NAMES:
            raise ValueError(f"unsupported datcompatibility value: {row!r}")
        compat = _COMPATIBILITY_NAMES[row.strip().upper()]
    except Exception as exc:
        raise sa_exc.InvalidRequestError(
            "Unable to detect GaussDB datcompatibility; refusing to assume "
            "A mode because that can generate invalid SQL"
        ) from exc
    return compat


def _quote_conninfo_value(value) -> str:
    """Quote one libpq conninfo value using PostgreSQL's DSN rules."""
    value = str(value)
    if value and not re.search(r"[\s'\\\\]", value):
        return value
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _conninfo_part(key, value) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)):
        raise sa_exc.ArgumentError(f"Invalid GaussDB connection option: {key!r}")
    if key not in _LIBPQ_CONNINFO_OPTIONS:
        raise sa_exc.ArgumentError(
            f"Unsupported GaussDB/libpq connection option: {key!r}"
        )
    return f"{key}={_quote_conninfo_value(value)}"


def _parse_catalog_int_vector(value) -> list[int]:
    """Normalize catalog int2[] / int2vector values without losing order.

    DBAPIs return these as lists/tuples, PostgreSQL array text, or a
    whitespace-separated int2vector. Some GaussDB builds also wrap array
    values in square brackets, e.g. ``{[2]}`` or ``{[3,2]}``.
    Invalid values must fail instead of silently dropping column numbers.
    """
    original = value

    def invalid():
        return ValueError(f"Invalid GaussDB catalog integer vector: {original!r}")

    def decode(item):
        if isinstance(item, (bytes, bytearray, memoryview)):
            try:
                return bytes(item).decode("ascii")
            except UnicodeDecodeError as exc:
                raise invalid() from exc
        return item

    integer = r"[+-]?[0-9]+"
    value = decode(value)
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            item = decode(item)
            if type(item) is int:
                result.append(item)
            elif isinstance(item, str) and re.fullmatch(integer, item.strip()):
                result.append(int(item))
            else:
                raise invalid()
        return result
    if not isinstance(value, str):
        raise invalid()

    body = value.strip()
    if body.startswith("{"):
        if not body.endswith("}"):
            raise invalid()
        body = body[1:-1].strip()
    if body.startswith("[") and body.endswith("]") and body.count("[") == body.count("]") == 1:
        body = body[1:-1].strip()
    if not body:
        return []
    if re.fullmatch(rf"{integer}(?:\s+{integer})*", body):
        return [int(item) for item in body.split()]

    # Also accept individually bracketed elements: {[3],[2]}.
    atom = rf"(?:{integer}|\[\s*{integer}\s*\])"
    if re.fullmatch(rf"{atom}(?:\s*,\s*{atom})*", body):
        return [int(item.strip().removeprefix("[").removesuffix("]")) for item in body.split(",")]
    raise invalid()


# ── Type compiler ────────────────────────────────────────────────────────────


class GaussDBTypeCompiler(PGTypeCompiler):
    """Adjust DDL type generation for M-compat (MySQL) mode."""

    def visit_TIMESTAMP(self, type_, **kw):
        compat = self.dialect.gaussdb_compatibility
        if compat == "M":
            if getattr(type_, "timezone", False):
                raise sa_exc.CompileError(
                    "GaussDB M mode has no timezone-aware TIMESTAMP type"
                )
            precision = getattr(type_, "precision", None)
            precision = precision if precision is not None else 6
            return f"TIMESTAMP({precision})"
        return super().visit_TIMESTAMP(type_, **kw)

    def visit_BOOLEAN(self, type_, **kw):
        if self.dialect.gaussdb_compatibility == "M":
            return "SMALLINT"
        return super().visit_BOOLEAN(type_, **kw)

    def visit_TIME(self, type_, **kw):
        if self.dialect.gaussdb_compatibility == "M":
            precision = getattr(type_, "precision", None)
            return f"TIME({precision})" if precision is not None else "TIME"
        return super().visit_TIME(type_, **kw)

    def visit_large_binary(self, type_, **kw):
        compat = self.dialect.gaussdb_compatibility
        if compat == "M":
            return "BLOB"
        return super().visit_large_binary(type_, **kw)


# ── DDL compiler ─────────────────────────────────────────────────────────────


class GaussDBDDLCompiler(PGDDLCompiler):
    """Adjust DDL for M-compat (MySQL) mode."""

    def get_column_specification(self, column, **kw):
        compat = self.dialect.gaussdb_compatibility
        # M mode: INTEGER AUTO_INCREMENT instead of SERIAL for PK
        if compat == "M" and column.autoincrement and column.primary_key:
            if isinstance(column.type, (sqltypes.SmallInteger, sqltypes.Integer, sqltypes.BigInteger)):
                coltype = self.dialect.type_compiler_instance.process(
                    column.type
                )
                default = " AUTO_INCREMENT"
                colname = self.preparer.quote(column.name)
                return f"{colname} {coltype} NOT NULL{default}"
        return super().get_column_specification(column, **kw)

    def visit_alter_column(self, alter, **kw):
        compat = self.dialect.gaussdb_compatibility
        if compat == "M":
            return self._visit_alter_column_m(alter, **kw)
        return super().visit_alter_column(alter, **kw)

    def _visit_alter_column_m(self, alter, **kw):
        """M-compat ALTER COLUMN uses MODIFY COLUMN syntax."""
        column = alter.column
        col_name = self.preparer.quote(column.name)

        if alter.modify_type is not None:
            col_type = self.dialect.type_compiler_instance.process(
                alter.modify_type
            )
            null_spec = "" if column.nullable else " NOT NULL"
            return f"ALTER TABLE {self.preparer.quote(alter.table.name)} " \
                   f"MODIFY COLUMN {col_name} {col_type}{null_spec}"

        if alter.modify_nullable is not None:
            null_spec = "NULL" if alter.modify_nullable else "NOT NULL"
            return f"ALTER TABLE {self.preparer.quote(alter.table.name)} " \
                   f"MODIFY COLUMN {col_name} {null_spec}"

        return super().visit_alter_column(alter, **kw)


# ── Identifier preparer ──────────────────────────────────────────────────────


class GaussDBIdentifierPreparer(PGIdentifierPreparer):
    """Use backticks for M-compat (MySQL) mode."""

    def __init__(self, dialect, **kwargs):
        super().__init__(dialect, **kwargs)
        compat = getattr(dialect, "gaussdb_compatibility", None)
        if compat == "M":
            # M-compat mode: use backticks instead of double quotes
            self.initial_quote = "`"
            self.final_quote = "`"
            self.escape_quote = "`"
            self.escape_to_quote = "``"
            self.reserved_words.update(
                [
                    "auto_increment", "engine", "charset", "collate",
                    "comment", "default", "key", "primary",
                ]
            )


# ── SQL compiler (concat fix) ────────────────────────────────────────────────


class GaussDBCompiler(PGCompiler):
    """Replace || with CONCAT() in M-compat mode."""

    def visit_expression_clauselist(self, clauselist, **kw):
        compat = getattr(self.dialect, "gaussdb_compatibility", None)
        if compat == "M":
            # Check if this is a concat operation
            if clauselist.operator is operators.concat_op:
                return self._m_concat(clauselist, **kw)
        return super().visit_expression_clauselist(clauselist, **kw)

    def visit_binary(self, binary, override_operator=None, **kw):
        operator = override_operator or binary.operator
        if (
            self.dialect.gaussdb_compatibility == "M"
            and operator is operators.concat_op
        ):
            left = self.process(binary.left, **kw)
            right = self.process(binary.right, **kw)
            return f"CONCAT({left}, {right})"
        return super().visit_binary(binary, override_operator=override_operator, **kw)

    def _m_concat(self, clauselist, **kw):
        args = []
        for clause in clauselist.clauses:
            args.append(self.process(clause, **kw))
        return "CONCAT(" + ", ".join(args) + ")"


# ── Execution contexts ──────────────────────────────────────────────────────


class GaussDBExecutionContext(PGExecutionContext):
    """Preserve ordinary INSERT counts before the DBAPI cursor is closed."""

    def post_exec(self):
        super().post_exec()
        # gaussdb resets cursor.rowcount on close. SQLAlchemy normally caches
        # UPDATE/DELETE counts, but may close a non-returning INSERT cursor
        # before the caller reads its count. Keep the actual server count,
        # including zero/unknown (-1); parameter count is not a substitute.
        # RETURNING and insertmanyvalues pagination retain SQLAlchemy's own
        # result handling so a last-page count cannot become a batch total.
        if (
            self.isinsert
            and not self._is_implicit_returning
            and not self._is_explicit_returning
            and self.execute_style is not ExecuteStyle.INSERTMANYVALUES
            and self._rowcount is None
        ):
            self._rowcount = self.cursor.rowcount


class GaussDBMExecutionContext(GaussDBExecutionContext):
    """Get auto-increment ID via LAST_INSERT_ID() in M-compat mode."""

    def get_lastrowid(self):
        try:
            cursor = self.cursor
            cursor.execute("select last_insert_id()")
            row = cursor.fetchone()
            if row and row[0] is not None:
                val = row[0]
                # Handle Java BigInteger from JDBC (shouldn't happen with psycopg3)
                if hasattr(val, "bit_length"):
                    return int(str(val))
                return int(val)
        except Exception:
            pass
        return None


# ── Dialect ──────────────────────────────────────────────────────────────────


class GaussDBDialect(PGDialect):
    """SQLAlchemy dialect for GaussDB using the gaussdb (psycopg3) DBAPI."""

    # Use psycopg3-style connection
    driver = "gaussdb"
    name = "gaussdb"

    ddl_compiler = GaussDBDDLCompiler
    type_compiler = GaussDBTypeCompiler
    preparer = GaussDBIdentifierPreparer
    statement_compiler = GaussDBCompiler
    execution_ctx_cls = GaussDBExecutionContext

    colspecs = dict(PGDialect.colspecs)
    colspecs.update({
        sqltypes.JSON: GaussDBJSON,
        JSON: GaussDBJSON,
        JSONB: GaussDBJSONB,
        sqltypes.LargeBinary: GaussDBLargeBinary,
        BYTEA: GaussDBBYTEA,
    })

    supports_statement_cache = True
    supports_native_enum = True
    supports_native_boolean = True
    supports_smallserial = True
    supports_sequences = True
    sequences_optional = True
    postfetch_lastrowid = False
    default_paramstyle = "pyformat"

    # Disable HSTORE (not assumed for lightweight GaussDB)
    use_native_hstore = False
    # Normalized GaussDB compatibility mode: 'A', 'B', 'M', or 'PG'
    gaussdb_compatibility = None

    # Register GaussDB M-compat binary types for reflection
    ischema_names = dict(PGDialect.ischema_names)
    ischema_names["blob"] = sqltypes.LargeBinary
    ischema_names["longblob"] = sqltypes.LargeBinary

    # ── DBAPI ────────────────────────────────────────────────────────────────

    # The default and ``+psycopg`` URLs use Huawei's psycopg3 fork.
    # Driver-specific subclasses override this value instead of mutating
    # shared class state at runtime.
    _driver_impl: str = "gaussdb"

    @classmethod
    def import_dbapi(cls):
        """Import Huawei's ``gaussdb`` DBAPI (the psycopg3 fork)."""
        try:
            import gaussdb
        except ImportError as exc:
            raise ImportError(
                "The gaussdb/psycopg3 dialect requires the 'gaussdb' package. "
                "Install with: pip install gaussdb"
            ) from exc
        return gaussdb

    @property
    def _is_psycopg3(self) -> bool:
        """True when the loaded driver is psycopg3 / gaussdb (psycopg3 fork)."""
        return self._driver_impl == "gaussdb"

    # ── Connection ───────────────────────────────────────────────────────────

    def create_connect_args(self, url):
        """Convert SQLAlchemy URL to driver connect() kwargs.

        psycopg3 (gaussdb/psycopg):
            connect(conninfo_string, prepare_threshold=None, cursor_factory=ClientCursor)
        psycopg2:
            connect(dsn_string)  — no prepare_threshold / cursor_factory
        """
        opts = url.translate_connect_args(username="user", database="dbname")
        opts.update(url.query)

        # Remove SQLAlchemy-specific params
        opts.pop("host", None)
        opts.pop("port", None)
        opts.pop("user", None)
        opts.pop("password", None)
        opts.pop("dbname", None)
        opts.pop("database", None)

        # Build conninfo string (works for both psycopg2 and psycopg3)
        parts = []
        if url.host:
            parts.append(_conninfo_part("host", url.host))
        if url.port:
            parts.append(_conninfo_part("port", url.port))
        if url.username:
            parts.append(_conninfo_part("user", url.username))
        if url.password:
            parts.append(_conninfo_part("password", url.password))
        if url.database:
            parts.append(_conninfo_part("dbname", url.database))

        # Pass through extra params (sslmode, etc.)
        for key, value in opts.items():
            parts.append(_conninfo_part(key, value))

        # Force UTF8 client encoding — GaussDB defaults to SQL_ASCII which
        # causes gaussdb/psycopg3 TextLoader to return bytes instead of str.
        if not any(k.startswith("client_encoding") for k, _ in opts.items()):
            parts.append("client_encoding=UTF8")

        conninfo = " ".join(parts)

        if self._is_psycopg3:
            # psycopg3 only: disable prepared statements entirely — psycopg3
            # auto-prepares after 5 executions and sends DEALLOCATE ALL on
            # transaction boundaries, which M-compat GaussDB rejects.
            # prepare_threshold=None disables the feature at the protocol level
            # so no DEALLOCATE is ever generated.  We also clear the cache on
            # commit/rollback as a belt-and-suspenders measure (see do_rollback
            # / do_commit).
            # Use ClientCursor to send parameters in text format — GaussDB's
            # binary protocol has issues with Numeric/BigInteger types.
            dbapi = self.dbapi or self.import_dbapi()
            return ([conninfo], {
                "prepare_threshold": None,
                "cursor_factory": dbapi.ClientCursor,
            })
        else:
            # psycopg2: default text protocol, no auto-prepare, no
            # DEALLOCATE ALL issue — just pass the conninfo string.
            return ([conninfo], {})

    # ── Initialization ───────────────────────────────────────────────────────

    def on_connect(self):
        # JSON is decoded by the DBAPI. Apply a user-supplied decoder there,
        # scoped to this connection (never change process-global adapters).
        parent = super().on_connect()
        if self._json_deserializer is None:
            return parent

        def configure_json(connection):
            if parent is not None:
                parent(connection)
            if self._is_psycopg3:
                from gaussdb.types.json import set_json_loads
                set_json_loads(self._json_deserializer, connection)
            else:
                from psycopg2.extras import register_default_json, register_default_jsonb
                register_default_json(connection, loads=self._json_deserializer)
                register_default_jsonb(connection, loads=self._json_deserializer)

        return configure_json

    def _get_server_version_info(self, connection):
        """Return a conservative version tuple for PGDialect feature gating.

        GaussDB's pg_catalog lacks many PostgreSQL 12+ columns
        (attgenerated, indnullsnotdistinct, etc.) that SQLAlchemy's
        reflection queries use when server_version_info >= (12,).
        Returning (9, 2) ensures those code paths are skipped, matching
        the actual PG-compat level of GaussDB's system catalogs.
        """
        return (9, 2)

    def initialize(self, connection):
        super().initialize(connection)
        self.gaussdb_compatibility = _detect_compatibility(connection)
        self._apply_compatibility_features()

    def _apply_compatibility_features(self):
        """Apply mode-specific dialect settings."""
        if self.gaussdb_compatibility == "M":
            # M mode: no RETURNING, use LAST_INSERT_ID
            self.insert_returning = False
            self.update_returning = False
            self.delete_returning = False
            self.postfetch_lastrowid = True
            self.execution_ctx_cls = GaussDBMExecutionContext
            # M mode: no native boolean (uses TINYINT)
            self.supports_native_boolean = False
        else:
            self.insert_returning = True
            self.update_returning = True
            self.delete_returning = True
            self.postfetch_lastrowid = False
            self.execution_ctx_cls = GaussDBExecutionContext
            self.supports_native_boolean = True

        # Re-create the identifier preparer now that gaussdb_compatibility
        # is known.  The preparer is instantiated during PGDialect.initialize()
        # (via super().initialize), before we set gaussdb_compatibility above,
        # so it defaults to PG-style double-quote quoting.  For M mode we need
        # backtick quoting.
        self.identifier_preparer = GaussDBIdentifierPreparer(self)

    def _gaussdb_connection(self, dbapi_conn):
        """Return the underlying gaussdb Connection from a pool wrapper.

        psycopg3 wraps connections in a ConnectionPool wrapper that exposes
        ``dbapi_connection()``.  psycopg2 connections are already raw DBAPI
        connections, so we return them as-is.
        """
        if not self._is_psycopg3:
            return dbapi_conn
        # psycopg3: SQLAlchemy may wrap the connection; unwrap to get raw DBAPI
        if hasattr(dbapi_conn, "dbapi_connection"):
            return dbapi_conn.dbapi_connection
        return dbapi_conn

    def _suppress_dealloc(self, dbapi_connection):
        """Compatibility no-op retained for older callers.

        Prepared statements are disabled through the public psycopg3
        ``prepare_threshold=None`` connection option.  Do not mutate the
        driver's private ``_prepared`` implementation here.
        """

    def do_rollback(self, dbapi_connection):
        self._suppress_dealloc(dbapi_connection)
        super().do_rollback(dbapi_connection)

    def do_commit(self, dbapi_connection):
        self._suppress_dealloc(dbapi_connection)
        super().do_commit(dbapi_connection)

    # ── Isolation level ──────────────────────────────────────────────────────

    def set_isolation_level(self, connection, level):
        compat = self.gaussdb_compatibility
        if compat == "M":
            # M mode: COMMIT before SET to avoid transaction conflicts
            connection.commit()
            # M mode: no "AS" keyword in SET SESSION CHARACTERISTICS
            level = level.upper().replace("_", " ")
            if level not in self.get_isolation_level_values(connection):
                raise sa_exc.ArgumentError(f"Invalid isolation level {level!r}")
            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"SET SESSION TRANSACTION ISOLATION LEVEL {level}"
                )
            finally:
                cursor.close()
        else:
            super().set_isolation_level(connection, level)

    # ── Reflection overrides ─────────────────────────────────────────────────
    #
    # GaussDB's pg_catalog differs from PostgreSQL in two ways that break
    # PGDialect's reflection queries:
    #
    # 1. A/B compat: the CASE WHEN ... (SELECT pg_type.typcollation ...) correlated
    #    subquery in _columns_query is rejected ("invalid reference to FROM-clause
    #    entry for table pg_type").
    #
    # 2. M compat: CAST(... AS TEXT) in _domain_query is rejected ("syntax error
    #    at or near TEXT").
    #
    # Solution: override get_columns with a simpler pg_catalog query that avoids
    # both problematic constructs.

    @reflection.cache
    def get_columns(self, connection, table_name, schema=None, **kw):
        return self._gaussdb_get_columns(connection, table_name, schema, **kw)

    def get_multi_columns(self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw):
        """Override PGDialect.get_multi_columns to use our safe query."""
        if filter_names:
            table_names = filter_names
        else:
            table_names = self.get_table_names(connection, schema=schema, scope=scope, kind=kind, **kw)

        result = {}
        for table_name in table_names:
            cols = self._gaussdb_get_columns(connection, table_name, schema, **kw)
            result[(schema, table_name)] = cols
        return result

    @reflection.cache
    def get_pk_constraint(self, connection, table_name, schema=None, **kw):
        """Override to avoid CAST AS TEXT in M-compat (PGDialect uses it in _constraint_query)."""
        compat = self.gaussdb_compatibility
        if compat != "M":
            return super().get_pk_constraint(connection, table_name, schema, **kw)

        # M compat: simple PK query without CAST AS TEXT
        if schema is None:
            schema = self.default_schema_name
        sql_text = """
            SELECT
                a.attname AS column_name,
                c.conname AS constraint_name
            FROM pg_catalog.pg_constraint c
            JOIN pg_catalog.pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            JOIN pg_catalog.pg_class cl ON cl.oid = c.conrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = cl.relnamespace
            WHERE c.contype = 'p'
                AND cl.relname = :table_name
                AND n.nspname = :schema
            ORDER BY a.attnum
        """
        result = connection.execute(
            text(sql_text),
            {"table_name": table_name, "schema": schema or "public"},
        )
        rows = list(result.mappings())
        cols = [row["column_name"] for row in rows]
        name = rows[0]["constraint_name"] if rows else None
        return {"constrained_columns": cols, "name": name, "comment": None}

    def get_multi_pk_constraint(self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw):
        """Override to avoid CAST AS TEXT in M-compat."""
        compat = self.gaussdb_compatibility
        if compat != "M":
            return super().get_multi_pk_constraint(connection, schema=schema, filter_names=filter_names, scope=scope, kind=kind, **kw)

        if filter_names:
            table_names = filter_names
        else:
            table_names = self.get_table_names(connection, schema=schema, scope=scope, kind=kind, **kw)

        result = {}
        for table_name in table_names:
            pk = self.get_pk_constraint(connection, table_name, schema=schema, **kw)
            result[(schema, table_name)] = pk
        return result

    # ── M-compat reflection: avoid CAST AS TEXT / REGCLASS ───────────────────

    def _m_simple_query(self, connection, sql, params):
        """Execute a raw SQL query and return mapped rows."""
        return connection.execute(text(sql), params).mappings().fetchall()

    @reflection.cache
    def get_unique_constraints(self, connection, table_name, schema=None, **kw):
        compat = self.gaussdb_compatibility
        if compat not in ("B", "M"):
            return super().get_unique_constraints(connection, table_name, schema, **kw)
        if schema is None:
            schema = self.default_schema_name
        # The backing index may contain distributed system attributes which
        # aren't part of the UNIQUE declaration. conkey is the logical key;
        # PostgreSQL's reflection query expands the physical index's indkey.
        # This simple query also avoids M-incompatible catalog SQL.
        sql_text = """
            SELECT c.conname AS name, c.conkey, c.conrelid,
                   pg_catalog.obj_description(c.oid, 'pg_constraint') AS comment
            FROM pg_catalog.pg_constraint c
            JOIN pg_catalog.pg_class cl ON cl.oid = c.conrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = cl.relnamespace
            WHERE c.contype = 'u'
              AND cl.relname = :table_name
              AND n.nspname = :schema
        """
        rows = self._m_simple_query(connection, sql_text, {"table_name": table_name, "schema": schema or "public"})
        result = []
        for r in rows:
            attnums = _parse_catalog_int_vector(r["conkey"])
            col_names = []
            for attnum in attnums:
                if attnum <= 0:
                    continue
                col_sql = "SELECT a.attname FROM pg_catalog.pg_attribute a WHERE a.attrelid = :relid AND a.attnum = :attnum"
                col_rows = self._m_simple_query(connection, col_sql, {"relid": r["conrelid"], "attnum": attnum})
                if col_rows:
                    name = col_rows[0]["attname"]
                    if isinstance(name, (bytes, bytearray)):
                        name = name.decode()
                    col_names.append(name)
            comment = r.get("comment")
            if isinstance(comment, (bytes, bytearray, memoryview)):
                comment = bytes(comment).decode()
            result.append({"name": r["name"], "column_names": col_names,
                           "duplicates_index": None, "comment": comment})
        return result

    @reflection.cache
    def get_table_comment(self, connection, table_name, schema=None, **kw):
        compat = self.gaussdb_compatibility
        if compat != "M":
            return super().get_table_comment(connection, table_name, schema, **kw)
        if schema is None:
            schema = self.default_schema_name
        sql_text = """
            SELECT d.description AS comment
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_description d ON d.objoid = c.oid AND d.objsubid = 0
            WHERE c.relname = :table_name AND n.nspname = :schema
        """
        rows = self._m_simple_query(connection, sql_text, {"table_name": table_name, "schema": schema or "public"})
        comment = rows[0]["comment"] if rows and rows[0]["comment"] else None
        return {"text": comment if not isinstance(comment, (bytes, bytearray)) else comment.decode() if comment else None}

    @reflection.cache
    def get_indexes(self, connection, table_name, schema=None, **kw):
        compat = self.gaussdb_compatibility
        if compat == "M":
            return self._m_get_indexes(connection, table_name, schema)
        return self._ab_get_indexes(connection, table_name, schema)

    def _m_get_indexes(self, connection, table_name, schema=None):
        if schema is None:
            schema = self.default_schema_name
        # M compat: avoid WITH ORDINALITY and array subscripting in JOIN
        sql_text = """
            SELECT cl.relname AS index_name,
                   idx.indisunique AS is_unique,
                   idx.indkey AS indkey,
                   idx.indrelid
            FROM pg_catalog.pg_index idx
            JOIN pg_catalog.pg_class cl ON cl.oid = idx.indexrelid
            JOIN pg_catalog.pg_class tbl ON tbl.oid = idx.indrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = tbl.relnamespace
            WHERE idx.indisprimary = false
              AND tbl.relname = :table_name
              AND n.nspname = :schema
        """
        rows = self._m_simple_query(connection, sql_text, {"table_name": table_name, "schema": schema or "public"})
        result = []
        for r in rows:
            attnums = _parse_catalog_int_vector(r["indkey"])
            col_names = []
            for attnum in attnums:
                # Negative numbers are system attributes (e.g. xc_node_hash,
                # ctid); zero is the expression slot handled as before.
                # Never filter by name: a positive attribute is a user column.
                if attnum <= 0:
                    continue
                col_sql = """
                    SELECT a.attname FROM pg_catalog.pg_attribute a
                    WHERE a.attrelid = :relid AND a.attnum = :attnum
                """
                col_rows = self._m_simple_query(connection, col_sql, {"relid": r["indrelid"], "attnum": attnum})
                if col_rows:
                    name = col_rows[0]["attname"]
                    if isinstance(name, (bytes, bytearray)):
                        name = name.decode()
                    col_names.append(name)
            result.append({
                "name": r["index_name"],
                "column_names": col_names,
                "unique": bool(r["is_unique"]),
                "include_columns": [],
                "dialect_options": {},
            })
        return result

    def get_multi_indexes(self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw):
        """Override to avoid CAST AS TEXT in M-compat and indoption type issues in A/B."""
        compat = self.gaussdb_compatibility

        if compat == "M":
            if filter_names:
                table_names = filter_names
            else:
                table_names = self.get_table_names(connection, schema=schema, scope=scope, kind=kind, **kw)
            result = {}
            for table_name in table_names:
                idxs = self._m_get_indexes(connection, table_name, schema)
                result[(schema, table_name)] = idxs
            return result

        # A/B compat: PGDialect.get_multi_indexes fails because gaussdb
        # returns indoption as string instead of int. Use per-table get_indexes.
        if filter_names:
            table_names = filter_names
        else:
            table_names = self.get_table_names(connection, schema=schema, scope=scope, kind=kind, **kw)
        result = {}
        for table_name in table_names:
            idxs = self._ab_get_indexes(connection, table_name, schema)
            result[(schema, table_name)] = idxs
        return result

    def _ab_get_indexes(self, connection, table_name, schema=None):
        """A/B compat index reflection without indoption bitwise ops."""
        if schema is None:
            schema = self.default_schema_name
        sql_text = """
            SELECT
                cl.relname AS index_name,
                idx.indisunique AS is_unique,
                idx.indisvalid AS is_valid,
                idx.indkey AS indkey,
                idx.indrelid,
                am.amname AS am_name
            FROM pg_catalog.pg_index idx
            JOIN pg_catalog.pg_class cl ON cl.oid = idx.indexrelid
            JOIN pg_catalog.pg_class tbl ON tbl.oid = idx.indrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = tbl.relnamespace
            LEFT JOIN pg_catalog.pg_am am ON am.oid = cl.relam
            WHERE idx.indisprimary = false
              AND tbl.relname = :table_name
              AND n.nspname = :schema
        """
        rows = self._m_simple_query(connection, sql_text, {"table_name": table_name, "schema": schema or "public"})
        result = []
        for r in rows:
            attnums = _parse_catalog_int_vector(r["indkey"])
            col_names = []
            for attnum in attnums:
                # Exclude physical system attributes, not same-named user
                # columns. Preserve the existing treatment of expression slots.
                if attnum <= 0:
                    continue
                col_rows = self._m_simple_query(connection,
                    "SELECT a.attname FROM pg_catalog.pg_attribute a WHERE a.attrelid = :relid AND a.attnum = :attnum",
                    {"relid": r["indrelid"], "attnum": attnum})
                if col_rows:
                    name = col_rows[0]["attname"]
                    if isinstance(name, (bytes, bytearray)):
                        name = name.decode()
                    col_names.append(name)
            is_unique = r["is_unique"]
            if isinstance(is_unique, (bytes, bytearray)):
                is_unique = is_unique.decode()
            result.append({
                "name": r["index_name"],
                "column_names": col_names,
                "unique": bool(is_unique),
                "include_columns": [],
                "dialect_options": {},
            })
        return result

    def get_multi_unique_constraints(self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw):
        """Use logical constraint keys consistently for B/M single and multi APIs."""
        compat = self.gaussdb_compatibility
        if compat not in ("B", "M"):
            return super().get_multi_unique_constraints(connection, schema=schema, filter_names=filter_names, scope=scope, kind=kind, **kw)

        if filter_names is not None:
            table_names = filter_names
        else:
            table_names = self.get_table_names(connection, schema=schema, scope=scope, kind=kind, **kw)

        result = {}
        for table_name in table_names:
            uqs = self.get_unique_constraints(connection, table_name, schema=schema, **kw)
            result[(schema, table_name)] = uqs
        return result

    def get_multi_foreign_keys(self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw):
        """Override to avoid CAST AS REGCLASS in M-compat."""
        compat = self.gaussdb_compatibility
        if compat != "M":
            return super().get_multi_foreign_keys(connection, schema=schema, filter_names=filter_names, scope=scope, kind=kind, **kw)

        if filter_names:
            table_names = filter_names
        else:
            table_names = self.get_table_names(connection, schema=schema, scope=scope, kind=kind, **kw)

        result = {}
        for table_name in table_names:
            fks = self.get_foreign_keys(connection, table_name, schema=schema, **kw)
            result[(schema, table_name)] = fks
        return result

    @reflection.cache
    def get_foreign_keys(self, connection, table_name, schema=None, **kw):
        """Override to avoid CAST AS REGCLASS in M-compat."""
        compat = self.gaussdb_compatibility
        if compat != "M":
            return super().get_foreign_keys(connection, table_name, schema, **kw)
        if schema is None:
            schema = self.default_schema_name
        # M compat: simple FK query without CAST AS REGCLASS
        sql_text = """
            SELECT c.conname AS name,
                   c.conkey,
                   c.confkey,
                   c.conrelid,
                   c.confrelid,
                   rn.nspname AS ref_schema,
                   rcl.relname AS ref_table
            FROM pg_catalog.pg_constraint c
            JOIN pg_catalog.pg_class cl ON cl.oid = c.conrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = cl.relnamespace
            JOIN pg_catalog.pg_class rcl ON rcl.oid = c.confrelid
            JOIN pg_catalog.pg_namespace rn ON rn.oid = rcl.relnamespace
            WHERE c.contype = 'f'
              AND cl.relname = :table_name
              AND n.nspname = :schema
        """
        rows = self._m_simple_query(connection, sql_text, {"table_name": table_name, "schema": schema or "public"})
        result = []
        for r in rows:
            con_attnums = _parse_catalog_int_vector(r["conkey"])
            conf_attnums = _parse_catalog_int_vector(r["confkey"])
            constrained_cols = []
            referred_cols = []
            for attnum in con_attnums:
                col_rows = self._m_simple_query(connection, "SELECT a.attname FROM pg_catalog.pg_attribute a WHERE a.attrelid = :relid AND a.attnum = :attnum", {"relid": r["conrelid"], "attnum": attnum})
                if col_rows:
                    n = col_rows[0]["attname"]
                    constrained_cols.append(n.decode() if isinstance(n, (bytes, bytearray)) else n)
            for attnum in conf_attnums:
                col_rows = self._m_simple_query(connection, "SELECT a.attname FROM pg_catalog.pg_attribute a WHERE a.attrelid = :relid AND a.attnum = :attnum", {"relid": r["confrelid"], "attnum": attnum})
                if col_rows:
                    n = col_rows[0]["attname"]
                    referred_cols.append(n.decode() if isinstance(n, (bytes, bytearray)) else n)
            result.append({
                "name": r["name"],
                "constrained_columns": constrained_cols,
                "referred_schema": r["ref_schema"] if r["ref_schema"] != "public" else None,
                "referred_table": r["ref_table"],
                "referred_columns": referred_cols,
                "options": {"ondelete": None, "onupdate": None, "deferrable": None, "initially": None, "match": None},
            })
        return result

    def get_multi_check_constraints(self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw):
        """Override to avoid CAST AS TEXT in M-compat."""
        compat = self.gaussdb_compatibility
        if compat != "M":
            return super().get_multi_check_constraints(connection, schema=schema, filter_names=filter_names, scope=scope, kind=kind, **kw)

        if filter_names:
            table_names = filter_names
        else:
            table_names = self.get_table_names(connection, schema=schema, scope=scope, kind=kind, **kw)

        result = {}
        for table_name in table_names:
            cks = self._m_get_check_constraints(connection, table_name, schema)
            result[(schema, table_name)] = cks
        return result

    @reflection.cache
    def get_check_constraints(self, connection, table_name, schema=None, **kw):
        compat = self.gaussdb_compatibility
        if compat != "M":
            return super().get_check_constraints(connection, table_name, schema, **kw)
        return self._m_get_check_constraints(connection, table_name, schema)

    def _m_get_check_constraints(self, connection, table_name, schema=None):
        if schema is None:
            schema = self.default_schema_name
        sql_text = """
            SELECT c.conname AS name,
                   pg_catalog.pg_get_constraintdef(c.oid) AS sqltext
            FROM pg_catalog.pg_constraint c
            JOIN pg_catalog.pg_class cl ON cl.oid = c.conrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = cl.relnamespace
            WHERE c.contype = 'c'
              AND cl.relname = :table_name
              AND n.nspname = :schema
        """
        rows = self._m_simple_query(connection, sql_text, {"table_name": table_name, "schema": schema or "public"})
        result = []
        for r in rows:
            sqltext = r["sqltext"]
            if isinstance(sqltext, (bytes, bytearray)):
                sqltext = sqltext.decode() if sqltext else None
            result.append({"name": r["name"], "sqltext": sqltext})
        return result

    def get_multi_table_comment(self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw):
        """Override to avoid CAST AS REGCLASS in M-compat."""
        compat = self.gaussdb_compatibility
        if compat != "M":
            return super().get_multi_table_comment(connection, schema=schema, filter_names=filter_names, scope=scope, kind=kind, **kw)

        if filter_names:
            table_names = filter_names
        else:
            table_names = self.get_table_names(connection, schema=schema, scope=scope, kind=kind, **kw)

        result = {}
        for table_name in table_names:
            tc = self.get_table_comment(connection, table_name, schema=schema, **kw)
            result[(schema, table_name)] = tc
        return result

    def _gaussdb_get_columns(self, connection, table_name, schema=None, **kw):
        """Custom column reflection that works across A/B/M compat modes."""
        compat = self.gaussdb_compatibility
        if schema is None:
            schema = self.default_schema_name

        # Build a simple query that avoids collation subquery and CAST AS TEXT
        sql_text = """
            SELECT
                a.attname AS name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS format_type,
                a.attnotnull AS not_null,
                a.atthasdef AS has_default,
                pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) AS default_expr,
                d.description AS comment,
                t.typname AS type_name,
                t.oid AS type_oid,
                a.attidentity AS identity
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_attribute a ON c.oid = a.attrelid
            JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
            LEFT JOIN pg_catalog.pg_attrdef ad
                ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
            LEFT JOIN pg_catalog.pg_description d
                ON d.objoid = a.attrelid AND d.objsubid = a.attnum
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = :table_name
                AND a.attnum > 0
                AND NOT a.attisdropped
                AND n.nspname = :schema
            ORDER BY a.attnum
        """

        result = connection.execute(
            text(sql_text),
            {"table_name": table_name, "schema": schema or "public"},
        )

        columns = []
        for row in result.mappings():
            col_name = row["name"]
            format_type = row["format_type"]
            col_type = self._resolve_type(format_type, row["type_oid"], compat)
            # GaussDB may return boolean as int or bytes; normalize
            raw_not_null = row["not_null"]
            if isinstance(raw_not_null, (bytes, bytearray)):
                raw_not_null = raw_not_null.decode() if raw_not_null else b""
            nullable = not bool(raw_not_null)
            raw_has_default = row["has_default"]
            if isinstance(raw_has_default, (bytes, bytearray)):
                raw_has_default = raw_has_default.decode() if raw_has_default else b""
            has_default = bool(raw_has_default)
            default_expr = row["default_expr"] if has_default else None
            raw_identity = row["identity"]
            if isinstance(raw_identity, (bytes, bytearray)):
                raw_identity = raw_identity.decode() if raw_identity else ""

            col_info = {
                "name": col_name,
                "type": col_type,
                "nullable": nullable,
                "default": text(default_expr) if default_expr else None,
                "comment": row["comment"] or None,
            }

            # Autoincrement detection
            if raw_identity and str(raw_identity) in ("a", "d"):
                col_info["autoincrement"] = True

            columns.append(col_info)

        return columns

    def _resolve_type(self, format_type, _type_oid, compat):
        """Map a pg_catalog.format_type string to a SQLAlchemy type."""
        ft = format_type.lower().strip()

        # M-compat type mappings
        if compat == "M":
            if ft in ("tinyint", "tinyint unsigned"):
                return sqltypes.SmallInteger()
            if ft in ("blob", "longblob", "mediumblob"):
                return sqltypes.LargeBinary()
            if ft == "datetime":
                return sqltypes.DateTime()
            if ft.startswith("datetime("):
                return sqltypes.DateTime()

        # Standard PG type mappings (works for A/B/M)
        type_map = {
            "integer": sqltypes.Integer,
            "bigint": sqltypes.BigInteger,
            "smallint": sqltypes.SmallInteger,
            "boolean": sqltypes.Boolean,
            "text": sqltypes.Text,
            "bytea": sqltypes.LargeBinary,
            "date": sqltypes.Date,
            "time without time zone": sqltypes.Time,
            "timestamp without time zone": sqltypes.DateTime,
            "timestamp with time zone": sqltypes.DateTime(timezone=True),
            "double precision": sqltypes.Float,
            "real": sqltypes.Float,
            "json": sqltypes.JSON,
            "jsonb": sqltypes.JSON,
        }

        # Handle character varying(N)
        if ft.startswith("character varying") or ft.startswith("varchar"):
            import re
            m = re.search(r"\((\d+)\)", ft)
            length = int(m.group(1)) if m else None
            return sqltypes.String(length=length) if length else sqltypes.String()

        # Handle numeric(p, s)
        if ft.startswith("numeric") or ft.startswith("decimal"):
            import re
            m = re.search(r"\((\d+),\s*(\d+)\)", ft)
            if m:
                return sqltypes.Numeric(int(m.group(1)), int(m.group(2)))
            return sqltypes.Numeric()

        # Handle timestamp(N)
        if ft.startswith("timestamp("):
            return sqltypes.DateTime()

        # Check exact match
        for key, type_cls in type_map.items():
            if ft == key:
                return type_cls()

        # Fallback: use String for unknown types
        return sqltypes.String()


# ── Registration ─────────────────────────────────────────────────────────────


def register_dialect():
    """Register the GaussDB dialect with SQLAlchemy.

    Registered dialect names:
    - ``gaussdb``         — Huawei gaussdb driver (psycopg3 fork)
    - ``gaussdb.psycopg`` — Huawei gaussdb driver (psycopg3 fork)
    - ``gaussdb.gaussdb`` — same as gaussdb.psycopg (alias)
    - ``gaussdb.psycopg2``— force psycopg2 driver
    """
    from sqlalchemy.dialects import registry

    registry.register(
        "gaussdb", "gaussdb_sqlalchemy.base", "GaussDBDialect"
    )
    registry.register(
        "gaussdb.psycopg", "gaussdb_sqlalchemy.base", "GaussDBDialect"
    )
    registry.register(
        "gaussdb.gaussdb", "gaussdb_sqlalchemy.base", "GaussDBDialect"
    )
    registry.register(
        "gaussdb.psycopg2", "gaussdb_sqlalchemy.base", "GaussDBDialect_psycopg2"
    )


class GaussDBDialect_psycopg2(GaussDBDialect):
    """GaussDB dialect pre-configured to use the psycopg2 driver.

    Use this when the user explicitly specifies ``gaussdb+psycopg2://`` in
    the connection URL.  It forces ``_driver_impl = "psycopg2"`` so that
    ``import_dbapi`` skips the gaussdb/psycopg3 probe and loads psycopg2
    directly — useful when both gaussdb (psycopg3) and psycopg2 are installed
    but the user wants psycopg2 (e.g. on ARM where psycopg2 2.9.10 is the
    fixed driver).
    """

    _driver_impl: str = "psycopg2"

    @classmethod
    def import_dbapi(cls):
        import psycopg2  # noqa: F401
        return psycopg2
