"""Bring the control database and every environment up to head.

Run from the entrypoint on every start. The control database goes first,
because that is where the list of environments lives — and on an upgraded
single-database install it *is* the first environment, so it gets migrated
once and skipped in the loop.

An environment that fails to migrate is reported and does not stop the
others: one broken city should not keep the rest of the operation offline.
"""

from __future__ import annotations

import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select

from app.db import CONTROL_DATABASE, ControlSession, control_engine, url_for


def _config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", url)
    return config


def _upgrade(label: str, url: str) -> bool:
    print(f"[migrate] {label}: upgrading to head")
    try:
        command.upgrade(_config(url), "head")
        return True
    except Exception as exc:  # noqa: BLE001 - report and carry on
        print(f"[migrate] {label}: FAILED — {exc}", file=sys.stderr)
        return False


def main() -> int:
    from app.config import settings

    if not _upgrade(f"control ({CONTROL_DATABASE})", settings.database_url):
        # Without the control database there is no list of environments and
        # no user table; there is nothing useful to carry on to.
        return 1

    # The environments table only exists once migration 0005 has run, which
    # the control upgrade above has just guaranteed. On a brand-new install it
    # is empty until the application registers the default on first start.
    if not inspect(control_engine).has_table("environments"):
        return 0

    from app.models import Environment

    session = ControlSession()
    try:
        rows = session.scalars(
            select(Environment).where(Environment.is_active.is_(True))
        ).all()
        targets = [r for r in rows if r.database_name != CONTROL_DATABASE]
    finally:
        session.close()

    failures = 0
    for environment in targets:
        if not _upgrade(
            f"{environment.key} ({environment.database_name})",
            url_for(environment.database_name),
        ):
            failures += 1

    if failures:
        print(
            f"[migrate] {failures} environment(s) failed; they will be "
            "unavailable until fixed.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
