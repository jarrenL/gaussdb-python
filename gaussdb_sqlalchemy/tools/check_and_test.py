"""Fail before pytest if a selected driver cannot load. Never print URLs."""
import importlib
import os
from pathlib import Path
import sys


def main():
    route = sys.argv[1]
    module = importlib.import_module("gaussdb" if route == "psycopg3" else "psycopg2")
    for name in ("connect", "paramstyle", "__version__"):
        if not hasattr(module, name):
            raise RuntimeError(f"Incomplete driver: missing {name}; module={module.__file__}")
    print("Driver:", module.__file__, module.__version__, module.paramstyle, flush=True)
    if route == "psycopg3":
        from gaussdb import pq, ClientCursor
        print("Implementation:", pq.__impl__, "libpq:", pq.version(), flush=True)
    from sqlalchemy import create_engine
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from gaussdb_sqlalchemy.base import register_dialect
    register_dialect()
    prefix = "gaussdb+psycopg://" if route == "psycopg3" else "gaussdb+psycopg2://"
    # Checks DBAPI attributes and dialect construction without a connection.
    engine = create_engine(prefix)
    engine.dispose()
    if sys.argv[2:] == ["--check-only"]:
        return
    url = os.environ.get("GAUSSDB_TEST_URL")
    if not url or not url.startswith(prefix):
        raise RuntimeError(f"Set GAUSSDB_TEST_URL using the {prefix} prefix")
    # A single route per process, even if the calling shell has a full matrix.
    for key in list(os.environ):
        if key.startswith("GAUSSDB_SQLALCHEMY_") and "URL" in key:
            del os.environ[key]
    os.environ["GAUSSDB_SQLALCHEMY_TEST_URL"] = url
    import pytest
    raise SystemExit(pytest.main([
        str(root / "gaussdb_sqlalchemy/tests/test_dialect_integration.py"),
        str(root / "gaussdb_sqlalchemy/tests/test_result_regressions_integration.py"),
        "-v", "-rs", *sys.argv[2:],
    ]))


if __name__ == "__main__":
    main()
