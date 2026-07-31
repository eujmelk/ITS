# Transit Scheduling

Implementation of [transit-architecture-v3.md](transit-architecture-v3.md).
FastAPI + PostgreSQL + React, packaged as three containers behind one port.

---

## Quick start

```powershell
Copy-Item .env.example .env
# Edit .env: SECRET_KEY, POSTGRES_PASSWORD and FIRST_ADMIN_PASSWORD have no
# usable defaults and the stack will refuse to start without them.
docker compose up --build
```

Then open <http://localhost:8080> and sign in with `FIRST_ADMIN_USERNAME` /
`FIRST_ADMIN_PASSWORD`.

Generate a real secret key with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Leave `SEED_DEMO_DATA=true` for the first run and you get a small worked
example — one line, two patterns, a weekday board with generated trips, a
valid block, two stops sharing a stop area, one explicit transfer. It is only
inserted into a completely empty database, so it can never touch real data.
Set it to `false` before you start entering anything you care about.

| URL | What |
| --- | --- |
| `http://localhost:8080` | The application |
| `http://localhost:8080/api/v1/docs` | Interactive API docs (Swagger) |
| `http://localhost:8080/api/v1/redoc` | Reference API docs |
| `http://localhost:8080/api/v1/health` | Liveness probe |

---

## What is built, and what is not

You asked for the backbone first, with rostering and the itinerary finder
stubbed behind their final API shapes. That is what this is.

**Complete — phases 1 to 9**

| Phase | Status |
| --- | --- |
| 1. Scaffolding | Docker, migrations, auth, roles |
| 2. Locations + attributes | Full CRUD, map, stop areas, transfers, quality checks |
| 3. Lines, patterns, pattern stops + attributes | Full CRUD, stop-list editor, pattern copy |
| 4. Schedule boards | Boards, calendars, exception dates, board copy |
| 5. Schedule within a board | Trip generation at a headway, timetable grid, per-trip editing, whole-trip shift |
| 6. Fares | Zones, the zone×zone matrix, bulk fill, live quoting |
| 7. PDF timetables | WeasyPrint, timepoint-only option, multi-page column splitting |
| 8. Fleet & interlined blocks | Vehicle types, vehicles, blocks, location-aware piece editor, consistency validator |
| 9. Settings | `parameters` CRUD, typed values, restore-defaults |

**Deliberately not built — phases 10 and 11**

- **Duty builder** (`/duties`, `/duties/{id}/pieces`, `/duties/{id}/validate`)
- **Itinerary search** (`/itinerary/search`)

These return **501** with an explanatory message rather than an empty `200`,
so nothing silently looks like "no data yet". Their request and response
models are final, the `duties` and `duty_pieces` tables already exist in the
database, and the things they depend on — validated blocks, and operating
parameters to check against — are finished. Adding them is filling in
handlers, not redesigning a contract.

One piece of phase 11 *is* built: the transfer graph
(`GET /api/v1/location-transfers/graph/edges`), because that is the part the
v3 revision actually changed. You can inspect it today on the Locations and
Itinerary pages.

**Added beyond the spec**, because they were cheap and the modules are
awkward without them:

- Trip generation at a fixed headway (`06:00–09:00 every 12 min`) — otherwise
  every trip is entered by hand.
- Whole-trip time shift that preserves running times.
- Board copy and pattern copy, for building next season from this one.
- Fare-matrix bulk fill and a live fare quote between two real stops.
- "Unassigned trips" work list with a *connects here* filter for block building.
- CSV exports (locations, stop times) and a data-quality report.
- Users, roles, and a bootstrap administrator.

---

## Decisions worth knowing about

**Times are integers, not `TIME` values.** Every schedule time is stored as
seconds since the start of the *service day*. A trip departing 01:10 as part
of Tuesday's service is `25:10:00`, which a SQL `TIME` column cannot
represent, and every duration and ordering check depends on getting this
right. The API speaks `"HH:MM:SS"` in both directions — see
[`app/timeutil.py`](backend/app/timeutil.py).

**Controlled vocabularies are `VARCHAR`, not PostgreSQL enums.** Adding a
value to a native enum needs a migration and an exclusive lock; here it is a
one-line change in [`app/enums.py`](backend/app/enums.py). Validation happens
in the Pydantic layer, which also matches the doc's preference for friendly
validation errors over hard database constraints.

**Validation reports, it does not block.** Block consistency, duty rules and
data quality all return a list of issues with a severity. A save always
succeeds, so an operator can knowingly accept an edge case — exactly as §4
step 5 of the architecture doc describes.

**Transfers are never inferred from coordinates.** The graph has exactly two
sources: stops sharing a `stop_area`, and explicit `location_transfers` rows.
Two points 40 m apart with a motorway between them are not connected unless
someone says so.

**Trip pieces in a block store nothing.** A `trip` piece's start and end
location and time are read back out of the trip's own `stop_times`. Only
deadhead / pull-out / pull-in pieces carry their own endpoints. The API
returns both, as `effective_*` fields, so the frontend never has to know which
kind it is looking at.

**Your two open questions from §10**, answered as follows — both are easy to
reverse:

1. *Per-line/per-driver parameter overrides?* Not yet. But every read goes
   through `parameters.resolve(db, key, scope=...)`, which already takes a
   scope it currently ignores. Adding a `parameter_overrides` table changes
   that one function and no caller.
2. *Must a block split between two drivers have a break at the hand-off?*
   A direct hand-off is allowed, and there is a parameter —
   `require_break_at_driver_changeover`, default `false` — that turns the
   requirement on when the duty builder lands.

---

## Layout

```
docker-compose.yml          db + api + web
backend/
  app/
    main.py                 app factory, lifespan bootstrap
    config.py               env-driven settings
    enums.py                controlled vocabularies
    timeutil.py             service-day time handling
    deps.py                 auth dependencies and role guards
    models/                 SQLAlchemy 2.0 models
    schemas/                Pydantic request/response models
    api/                    routers, one module per domain
    services/
      crud.py               generic CRUD router factory
      blocks.py             piece resolution + consistency validator
      transfers.py          the walking-transfer graph
      timetable.py          the stops-down / trips-across grid
      trips.py              generation, stop times, shifting
      parameters.py         parameter resolution (scope-ready)
      pdf.py, seed.py
    templates/timetable.html
  alembic/                  migrations
  tests/
frontend/
  src/
    api/                    fetch client + shared types
    components/             Crud factory, ui kit, map, attribute editor
    pages/                  one per module
  nginx.conf                serves the SPA, proxies /api to the api container
```

Twelve modules with near-identical list/get/create/update/delete endpoints is
twelve chances to build an inconsistent one, so both sides have a factory:
`crud_router()` on the backend and `<CrudTable>` on the frontend. Each module
then adds only what is genuinely specific to it.

---

## Development without Docker

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
$env:DATABASE_URL = "postgresql+psycopg://transit:transit@localhost:5432/transit"
$env:SECRET_KEY = "dev"
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend (proxies `/api` to `localhost:8000`):

```powershell
cd frontend
npm install
npm run dev
```

### Tests

```powershell
cd backend
pytest
```

They run against SQLite, so no container is needed — every column type in the
models is portable. Two caveats: SQLite does not enforce foreign keys by
default, so cascade behaviour is not covered; and `test_pdf_timetable_renders`
needs WeasyPrint's pango/cairo libraries, which are installed in the API image
but probably not on a bare Windows host. To run the suite in the same
environment as production:

```powershell
docker compose run --rm api sh -c "pip install -r requirements-dev.txt && pytest"
```

### Type-checking the frontend

The Docker build runs `vite build`, which transpiles without type-checking, so
a type nit can never break a deployment. Check types explicitly:

```powershell
cd frontend
npm run typecheck
```

---

## Migrations

Revision `0001` creates the schema from `Base.metadata` rather than from ~25
hand-written `create_table` calls. The result is exactly the schema the models
describe, which removes any chance of drift between revision 1 and the ORM.

From revision 2 onward, use the normal workflow — autogenerate works correctly
against a database created this way precisely because the two are identical:

```powershell
docker compose exec api alembic revision --autogenerate -m "add something"
docker compose exec api alembic upgrade head
```

Migrations run automatically on container start, before uvicorn.

---

## Production notes

Before this faces anything real:

1. **Set `SECRET_KEY` to a random value.** Every issued token is signed with
   it; changing it later logs everyone out, which is the point if it leaks.
2. **Change the bootstrap admin password** on first login, and set
   `SEED_DEMO_DATA=false`.
3. **Stop publishing the database port.** Comment out the `ports:` block on
   the `db` service so PostgreSQL is only reachable inside the compose
   network.
4. **Put TLS in front of it.** The `web` container serves plain HTTP on port
   80; terminate TLS at a reverse proxy (Traefik, nginx, an ingress) and
   forward to it. Bearer tokens over plain HTTP on a shared network are
   readable by anyone on the path.
5. **Back up the `pgdata` volume**, not the containers:
   `docker compose exec -T db pg_dump -U transit transit > backup.sql`
6. **Point `MAP_TILE_URL` at an internal tile server** if the host has no
   outbound internet — the map is the only thing that reaches out, and it
   degrades to an empty grey canvas rather than failing.

### Roles

| Role | Can |
| --- | --- |
| `viewer` | Read everything, export PDF and CSV |
| `planner` | The above, plus edit network, schedule, fare and block data |
| `admin` | The above, plus manage users and operating parameters |

You cannot disable, demote or delete your own account, and the last
administrator cannot be removed.
