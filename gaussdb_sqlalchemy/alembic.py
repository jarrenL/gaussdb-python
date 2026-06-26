"""
Alembic integration for GaussDB SQLAlchemy dialect.

Registers an Alembic implementation that handles M-compat (MySQL) mode
differences in ALTER TABLE syntax.
"""
from __future__ import annotations


def register_alembic_impl():
    """Register GaussDB-specific Alembic implementation."""
    try:
        from alembic.ddl import postgresql as pg_impl
        from alembic.ddl.base import ColumnNullable, ColumnType
        from alembic.ddl.impl import DefaultImpl, _impls
        from sqlalchemy.ext.compiler import compiles

        # Register dialect name "gaussdb" in Alembic's impl registry
        if "gaussdb" not in _impls:

            class GaussDBImpl(pg_impl.PostgresqlImpl):
                __dialect__ = "gaussdb"

                def alter_column(self, table_name, column_name, **kw):
                    """Override to intercept M-compat ALTER COLUMN."""
                    compat = getattr(self.dialect, "gaussdb_compatibility", None)
                    new_name = kw.get("name", None)
                    type_ = kw.get("type_", None)
                    nullable = kw.get("nullable", None)

                    if compat == "M":
                        existing_type = kw.get("existing_type", None)
                        existing_nullable = kw.get("existing_nullable", None)
                        schema = kw.get("schema", None)

                        # Determine the type to use for MODIFY/CHANGE
                        col_type = type_ or existing_type
                        if col_type is not None:
                            # Get type DDL string via the dialect's type compiler
                            try:
                                type_text = self.dialect.type_compiler_instance.process(col_type)
                            except Exception:
                                type_text = "TEXT"

                            if new_name is not None and new_name != column_name:
                                # M compat: RENAME via CHANGE COLUMN old new <type>
                                table_ref = self.dialect.identifier_preparer.quote(table_name)
                                old_ref = self.dialect.identifier_preparer.quote(column_name)
                                new_ref = self.dialect.identifier_preparer.quote(new_name)
                                self._exec(f"ALTER TABLE {table_ref} CHANGE COLUMN {old_ref} {new_ref} {type_text}")
                            elif type_ is not None:
                                # M compat: type change via MODIFY COLUMN
                                table_ref = self.dialect.identifier_preparer.quote(table_name)
                                col_ref = self.dialect.identifier_preparer.quote(column_name)
                                self._exec(f"ALTER TABLE {table_ref} MODIFY COLUMN {col_ref} {type_text}")
                        elif new_name is not None and new_name != column_name:
                            # Rename without type info — need existing type
                            if col_type is None and existing_type is not None:
                                col_type = existing_type
                            if col_type is not None:
                                type_text = self.dialect.type_compiler_instance.process(col_type)
                                table_ref = self.dialect.identifier_preparer.quote(table_name)
                                old_ref = self.dialect.identifier_preparer.quote(column_name)
                                new_ref = self.dialect.identifier_preparer.quote(new_name)
                                self._exec(f"ALTER TABLE {table_ref} CHANGE COLUMN {old_ref} {new_ref} {type_text}")

                        if nullable is not None:
                            col_ref = self.dialect.identifier_preparer.quote(new_name or column_name)
                            table_ref = self.dialect.identifier_preparer.quote(table_name)
                            null_spec = "NULL" if nullable else "NOT NULL"
                            # M compat: MODIFY COLUMN col NULL/NOT NULL — but M requires type
                            if col_type is not None:
                                try:
                                    type_text = self.dialect.type_compiler_instance.process(col_type)
                                except Exception:
                                    type_text = "TEXT"
                                self._exec(f"ALTER TABLE {table_ref} MODIFY COLUMN {col_ref} {type_text} {null_spec}")
                            else:
                                self._exec(f"ALTER TABLE {table_ref} MODIFY COLUMN {col_ref} {null_spec}")
                        return

                    # A/B compat: use PostgreSQL syntax
                    super().alter_column(table_name, column_name, **kw)

            _impls["gaussdb"] = GaussDBImpl

        # Compile handlers for base ColumnType (used by GaussDBImpl.alter_column)
        @compiles(ColumnType, "gaussdb")
        def _gaussdb_column_type(element, compiler, **kw):
            dialect = kw.get("dialect")
            compat = getattr(dialect, "gaussdb_compatibility", None) if dialect else None

            if compat == "M":
                table_name = compiler.preparer.quote(element.table_name)
                col_name = compiler.preparer.quote(element.column_name)
                col_type = element.column.type
                type_text = dialect.type_compiler_instance.process(col_type) if dialect else ""
                return f"ALTER TABLE {table_name} MODIFY COLUMN {col_name} {type_text}"

            # A/B compat: use standard ALTER COLUMN TYPE
            table_name = compiler.preparer.quote(element.table_name)
            col_name = compiler.preparer.quote(element.column_name)
            col_type = element.column.type
            type_text = dialect.type_compiler_instance.process(col_type) if dialect else ""
            return f"ALTER TABLE {table_name} ALTER COLUMN {col_name} TYPE {type_text}"

        @compiles(ColumnNullable, "gaussdb")
        def _gaussdb_column_nullable(element, compiler, **kw):
            dialect = kw.get("dialect")
            compat = getattr(dialect, "gaussdb_compatibility", None) if dialect else None

            if compat == "M":
                table_name = compiler.preparer.quote(element.table_name)
                col_name = compiler.preparer.quote(element.column_name)
                null_spec = "NULL" if element.nullable else "NOT NULL"
                return f"ALTER TABLE {table_name} MODIFY COLUMN {col_name} {null_spec}"

            # A/B compat: standard ALTER COLUMN SET/DROP NOT NULL
            table_name = compiler.preparer.quote(element.table_name)
            col_name = compiler.preparer.quote(element.column_name)
            null_spec = "DROP NOT NULL" if element.nullable else "SET NOT NULL"
            return f"ALTER TABLE {table_name} ALTER COLUMN {col_name} {null_spec}"

        # Also register PostgresqlColumnType for A/B compat (renders ALTER COLUMN TYPE ... USING)
        try:
            PostgresqlColumnType = pg_impl.PostgresqlColumnType

            @compiles(PostgresqlColumnType, "gaussdb")
            def _gaussdb_pg_column_type(element, compiler, **kw):
                dialect = kw.get("dialect")
                compat = getattr(dialect, "gaussdb_compatibility", None) if dialect else None

                if compat == "M":
                    table_name = compiler.preparer.quote(element.table_name)
                    col_name = compiler.preparer.quote(element.column_name)
                    col_type = element.column.type
                    type_text = dialect.type_compiler_instance.process(col_type) if dialect else ""
                    return f"ALTER TABLE {table_name} MODIFY COLUMN {col_name} {type_text}"

                # A/B compat: delegate to PG's visit_column_type
                return pg_impl.visit_column_type(element, compiler, **kw)

        except AttributeError:
            pass

    except ImportError:
        # Alembic not installed
        pass
