# GaussDB SQLAlchemy dialect tests
#
# Two test categories:
# 1. Unit tests (test_dialect_unit.py) — no database needed, test driver detection,
#    connect args, dialect registration, psycopg2/psycopg3 branching
# 2. Integration tests (test_dialect_integration.py) — require a live GaussDB instance,
#    test CRUD, reflection, M-compat, Alembic, transactions
