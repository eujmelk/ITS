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

## What is built

All twelve phases of §9.

| Phase | Status |
| --- | --- |
| 1. Scaffolding | Docker, migrations, auth, roles |
| 2. Locations + attributes | Full CRUD, map, stop areas, transfers, quality checks |
| 3. Lines, patterns, pattern stops + attributes | Full CRUD, stop-list editor, pattern copy |
| 4. Schedule boards | Boards, calendars, exception dates, board copy |
| 5. Schedule within a board | Trip generation at a headway, timetable grid, per-trip editing, whole-trip shift |
| 6. Fares | Zones, the zone×zone matrix, bulk fill, live quoting |
| 7. PDF timetables | WeasyPrint, all stops with timepoints in bold, multi-page column splitting |
| 8. Fleet & interlined blocks | Vehicle types, vehicles, blocks, location-aware piece editor, consistency validator |
| 9. Settings | `parameters` CRUD, typed values, restore-defaults |
| 10. Full rostering | Duty builder, block splitting, break rules, coverage report, detailed duty-card PDFs |
| 11. Itinerary finder | Connection-scan search over the stop-area/transfer graph |
| 12. Polish | CSV exports, PDF styling, pagination and search throughout |
| 13. GTFS export *(beyond the doc)* | Standards-compliant feed per board, with pre-flight checks |

**Added beyond the spec**, because they were cheap and the modules are
awkward without them:

- Trip generation at a fixed headway (`06:00–09:00 every 12 min`) — otherwise
  every trip is entered by hand.
- Whole-trip time shift that preserves running times.
- Board copy and pattern copy, for building next season from this one.
- Fare-matrix bulk fill and a live fare quote between two real stops.
- "Unassigned trips" work list with a *connects here* filter for block building.
- Block coverage report: which pieces of which blocks still have no driver.
- Driver double-booking and relief-handover checks on top of the §5 rules.
- CSV exports (locations, stop times) and a data-quality report.
- Users, roles, and a bootstrap administrator.
- **Stop skipping**: clearing a stop's times on a trip makes it run past
  without calling, which is how a limited-stop or short working is built
  without cloning the whole pattern. Stored as the *absence* of a stop time,
  so the timetable shows a gap and exports leave it out — rather than a call
  at 00:00 that quietly corrupts the feed.
- **Pattern attributes** — see the section below; this is a deliberate
  deviation from §2 of the architecture doc.
- **Editable instance name.** The name in the sidebar, on the login page and
  in the browser tab is the `instance_name` setting, not an env var, so it can
  be changed without a redeploy. The agency details next to it are what GTFS
  needs.

## Attributes belong to patterns, not lines

**This differs from §2 of the architecture doc**, which put generic
attributes on `lines`. In practice they describe a *variant* of a service —
express, school-days-only, via the hospital — and those differ between a
line's patterns rather than applying to all of them. Having both levels was
ambiguous: nothing said which one won when they disagreed. So `line_attributes`
is gone and `pattern_attributes` replaces it.

Migration `0004` copies any existing line attributes onto that line's patterns
before dropping the table, so nothing already entered is lost. A pattern that
already defines the same key keeps its own value — the more specific statement
wins. Locations keep their attributes unchanged; a stop is a single thing with
no variants.

Each non-empty **value** prints as an outlined bubble beside the line number —
a duty card shows (127) (EXP), and a combined timetable puts it above the
column. Outlined rather than solid, so it reads as a qualifier on the line
rather than as another line number.

**Two keys are reserved because GTFS has real fields for them:**
`wheelchair_accessible` and `bikes_allowed`. Their values are validated on
write (`yes` / `no` / `unknown`, plus the obvious synonyms), so a feed can
never be built with `wheelchair_accessible=maybe` in it, and they are exported
into `trips.txt` rather than silently dropped. A value set on the trip itself
still beats the pattern's default. These two are *not* printed as bubbles —
"yes" beside a line number tells a driver nothing.

Everything else is internal. GTFS has nowhere to carry "TYPE=EXP", and
smuggling it into a field that means something else would produce a feed that
lies. `GET /api/v1/pattern-attributes/reserved/gtfs` lists what is reserved.

## Printed output

**Timetables can combine patterns.** A line's express and stopping variants
belong on one sheet, not two — a passenger reads a single column of stops.
Tick several patterns and their stop lists are merged: the longest becomes the
spine, and stops the others add are folded in at their anchored positions. A
stop only some variants serve is marked "◦", and each column carries the
attribute bubbles of the pattern its trip runs. Combining patterns of
different lines is refused — that is a different route wanting its own sheet.

**Timetables** print every stop on the pattern, not only the timepoints.
Timepoints are what a reader navigates by, so they carry the weight — bold,
ruled above and below, and marked in the line colour — while intermediate
stops stay legible but recede. Wide boards split across pages with the stop
column repeated. `timepoints_only=true` still gives the old condensed sheet if
you want it for a public display case.

**Duty cards** are Letter portrait, one duty per card: header with agency,
duty, date and driver; an information strip (sign on, sign off, spread,
driving, break); then the duty in detail. A block segment is *not* printed as
"drive block B01" — it is expanded into its actual legs: each trip with its
line, headsign and timepoints, each deadhead and pull-out/pull-in with its
endpoints, and the turnaround time between them. Rule-check errors and
warnings are printed at the foot; informational notes are not, because they
are noise on paper. There is a signature line.

## GTFS export

`GTFS` on any board builds a standards-compliant zip: `agency`, `stops`,
`routes`, `trips`, `stop_times`, `calendar`, `calendar_dates`, `transfers`,
`fare_attributes`, `fare_rules`, `feed_info`. The mapping is close to
one-to-one because the v3 model was already shaped like GTFS. Three places
where it deliberately is not:

- **Only passenger-facing data.** Depots, garages, layover points, blocks and
  duties are operational and stay internal.
- **Stop areas become parent stations**, which is what GTFS uses them for.
  Their members are therefore *not* also written to `transfers.txt` — that
  would be redundant and would lose the "these are the same place" meaning.
  Explicit pairwise transfers are written, both directions.
- **`stop_sequence` is renumbered densely per trip.** A trip that skips stops
  would otherwise leave gaps; legal, but readers differ on how they treat
  them.

A pre-flight check runs first and reports what would make a strict reader
reject the feed (no `agency_url`, no timezone, stops without coordinates, a
board with no trips). Exporting anyway is allowed — a feed missing an agency
URL is still useful for inspecting the data.

## Built for real data volumes

A network is tens of thousands of rows, and a UI that quietly loads "the first
thousand" is worse than one that fails loudly. So:

- **Every list is paged server-side** and reports the unpaged total — the grid
  says "Showing 51–100 of 4,312", never a truncated list dressed up as a
  complete one. Column headers sort server-side; search is debounced.
- **Foreign keys are searchable pickers, not dropdowns.** A `<select>` with
  every stop in it is one oversized response and thousands of DOM nodes, and
  the block editor would render one per piece row. `EntitySelect` queries the
  server as you type and holds 25 options at a time, with a shared label cache
  so twenty pieces pointing at the same depot cost one request.
- **The timetable pages its trip columns.** A high-frequency pattern runs 250+
  trips a day; the grid loads 40 columns at a time, ordered by departure
  *before* slicing, and fetches stop times only for the visible ones.
- **The map draws only what is in view**, capped at 750 markers, and says so
  when it is holding some back.
- **The block builder's "connects here" filter runs in the database**, not in
  the browser — that shortlist is a handful of trips out of a board's
  thousands.
- **Trip endpoints are resolved with a window function**, so building a block
  reads two rows per trip instead of every stop time on the board.
- The fare matrix is quadratic in zones by nature; past 25 zones it asks
  before rendering and points at bulk-fill instead.

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

**The itinerary search is a Connection Scan**, not a graph search: every trip
is chopped into stop-to-stop connections, sorted by departure, and one forward
pass fixes the earliest arrival everywhere. It is easy to check against a
printed timetable by hand, which matters more here than raw speed — a service
day is a small enough scan for that trade to be free.

One wrinkle worth knowing: earliest-arrival labelling has an artifact where
walking away from the origin the moment the search window opens reaches a
neighbouring stop hours before any vehicle, so every journey through that stop
gets reconstructed as "walk, wait an hour, ride" even when boarding at the
origin arrives at the same time. The scan is therefore run both with and
without origin footpaths, keeping whichever journey is better on (arrival,
number of legs). Walks are also scheduled as late as they can go, so a
connection reads as "leave at 08:56, walk 4 minutes, board at 09:00".

**Your two open questions from §10**, answered as follows — both are easy to
reverse:

1. *Per-line/per-driver parameter overrides?* Not implemented. But every read
   goes through `parameters.resolve(db, key, scope=...)`, which already takes
   a scope it currently ignores. Adding a `parameter_overrides` table changes
   that one function and no caller.
2. *Must a block split between two drivers have a break at the hand-off?*
   A direct hand-off is allowed and reported as an informational
   `RELIEF_WITHOUT_BREAK` note. Setting the
   `require_break_at_driver_changeover` parameter to `true` promotes it to an
   error. Both are live — see `test_direct_handover_is_allowed_but_flagged`.

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
      crud.py               generic CRUD router factory (paging, sort, search)
      blocks.py             piece resolution + consistency validator
      duties.py             duty resolution + the §5 rule checks
      transfers.py          the walking-transfer graph
      timetable.py          the stops-down / trips-across grid
      trips.py              generation, stop times, shifting
      calendars.py          which services run on a given date
      itinerary.py          connection-scan journey search
      parameters.py         parameter resolution (scope-ready)
      pdf.py, seed.py
    templates/              timetable.html, duty_card.html
  alembic/                  migrations
  tests/
frontend/
  src/
    api/                    fetch client + shared types
    components/             Crud factory (paged table), EntitySelect,
                            ui kit, map, attribute editor
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
