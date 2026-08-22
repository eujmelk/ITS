#!/bin/sh
set -e

echo "[entrypoint] waiting for database..."
python - <<'PY'
import os, sys, time
import sqlalchemy

url = os.environ["DATABASE_URL"]
deadline = time.time() + 120
last = None
while time.time() < deadline:
    try:
        engine = sqlalchemy.create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        engine.dispose()
        print("[entrypoint] database is up")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - any connection failure is a retry
        last = exc
        time.sleep(2)
print(f"[entrypoint] database unreachable after 120s: {last}", file=sys.stderr)
sys.exit(1)
PY

# The control database plus every registered environment. One failing
# environment is reported but does not hold the others offline.
echo "[entrypoint] applying migrations..."
python -m scripts.migrate_all

echo "[entrypoint] starting: $*"
exec "$@"
