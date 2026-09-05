#!/usr/bin/env bash
# Run each DBAPI in a fresh process with a route-specific library path.
set -euo pipefail
route=${1:?Usage: bash run_driver_test.sh psycopg2|psycopg3 [--check-only]}
shift
root=$(cd "$(dirname "$0")/../.." && pwd)
py=${PYTHON_BIN:-python3}
case "$route" in
  psycopg3)
    : "${GAUSSDB_LIB_DIR:?Set GAUSSDB_LIB_DIR to the matching GaussDB client lib directory}"
    test -f "$GAUSSDB_LIB_DIR/libpq.so.5" || { echo 'Missing libpq.so.5' >&2; exit 1; }
    export LD_LIBRARY_PATH="$GAUSSDB_LIB_DIR${GAUSSDB_EXTRA_LIB_DIRS:+:$GAUSSDB_EXTRA_LIB_DIRS}"
    export GAUSSDB_IMPL=python
    export GAUSSDB_LIBPQ_PATH="$GAUSSDB_LIB_DIR/libpq.so.5"
    ;;
  psycopg2)
    # Do not inherit the psycopg3 process library search path.
    unset LD_LIBRARY_PATH GAUSSDB_IMPL GAUSSDB_LIBPQ_PATH
    if test -n "${PSYCOPG2_EXTRA_LIB_DIRS:-}"; then
      export LD_LIBRARY_PATH="$PSYCOPG2_EXTRA_LIB_DIRS"
    fi
    ;;
  *) echo 'Expected psycopg2 or psycopg3' >&2; exit 2 ;;
esac
unset LD_PRELOAD
exec "$py" "$root/gaussdb_sqlalchemy/tools/check_and_test.py" "$route" "$@"
