# Transit Scheduling Software — Architecture Plan (v3)

Revision notes vs. v2: stops generalized into `locations` (covers depots and
layover points, not just passenger stops), generic extensible attributes
for both locations and lines, `block_pieces` now reference real locations
instead of free text, full duty/roster builder (assign blocks to drivers,
insert breaks, split shifts across partial blocks), and a global
`parameters` table for driving-time/break rules. Fare-by-zone confirmed as
already matching the v2 design — no change there.

---

## 1. Locations (generalizes "stops")

Depots and layover areas are operationally the same kind of thing as a
passenger stop — a place with a name and coordinates — so this collapses
into one table with a type flag rather than three separate tables.

**`locations`**
- `id`, `name`, `code` (nullable), `location_type`
  (`stop` / `depot` / `layover` / `garage` / `other`), `lat`, `lon`,
  `zone_id` (nullable — depots/layovers typically don't need a fare zone,
  but it's allowed in case you ever want to fare a trip that starts there)

**`location_attributes`** (generic key/value, so you're not blocked
waiting on schema changes every time you think of a new attribute you
want to track)
- `location_id`, `attribute_key`, `attribute_value`

Suggested seed keys for `stop`-type locations: `has_shelter`, `has_bench`,
`wheelchair_accessible`, `lit`, `park_and_ride`, `platform_count`. For
`depot`-type: `capacity`, `fuel_type_supported`. These are just sensible
starting rows, not hardcoded columns — add/remove keys freely from the UI.

`pattern_stops` continues to reference `locations` but should only ever
point at `location_type = 'stop'` rows (enforced in the service layer, not
the DB, so it's a friendly validation error rather than a hard constraint).

`block_pieces.from_location_id` / `to_location_id` (see §3) can reference
*any* location type — this is exactly how deadhead/pull-out/pull-in legs
get modeled properly instead of as free text.

---

## 1a. Stop Areas & Transfers

The problem: two distinct `locations` (e.g. opposite sides of an
intersection, or two directions of the same street) can be close enough
that a rider would happily transfer between them, but they're genuinely
separate stops with separate patterns serving them. This needs an explicit
model rather than relying on lat/lon proximity, since "close on the map"
and "actually easy to walk between" aren't the same thing (a highway or a
river can sit between two nearby-looking coordinates).

Two mechanisms, covering the tight case and the loose case:

**`stop_areas`** — a named grouping of locations that are effectively "the
same place" (this mirrors GTFS's `parent_station` concept). Use this for
the common case you described: two directions of the same street, opposite
corners of the same intersection.
- `id`, `name` (e.g. "Strawberry Rd & Main St"), `default_transfer_seconds`
  (e.g. 90–120s to cover crossing the street)

`locations` gains a nullable `area_id` FK. Any two `stop`-type locations
sharing an `area_id` are automatically treated as connected by a transfer
of `default_transfer_seconds` — you flag membership once per stop, not
once per pair, so adding a third stop to the same corner doesn't require
wiring up new pairwise transfers.

**`location_transfers`** — explicit pairwise transfers for anything that
isn't really "the same place" but is still a reasonable walking connection
(e.g. a bus stop and a rail platform 300m apart at a multimodal hub, or
two areas that are close but separated enough you want a longer, specific
walk time rather than the area default).
- `id`, `from_location_id`, `to_location_id`, `walk_seconds`,
  `distance_m` (optional), `is_bidirectional` (default true)

**How the itinerary finder uses this:** when building the transfer step of
the search, for each stop the router considers three sources of walking
edges: (1) other stops in the same `stop_area`, at
`default_transfer_seconds`, (2) any row in `location_transfers` involving
that stop, at its specific `walk_seconds`, (3) nothing else — it does not
infer transfers from raw coordinate proximity, so you stay in control of
what's actually flagged as connected.

**UI**: a "Stop Areas" panel on LocationsPage — create an area, multi-select
which stop locations belong to it, set the default cross time. A separate
lightweight "Transfers" table for the explicit pairwise cases, since those
should be rarer and don't need the full area-management UI.

---

## 2. Lines — Generic Attributes

**`line_attributes`** (same generic key/value pattern)
- `line_id`, `attribute_key`, `attribute_value`

Suggested seed keys: `wheelchair_accessible`, `peak_only`, `night_service`,
`seasonal`, `express`, `operator_notes`.

(Patterns/pattern_stops/schedule_versions/calendars/trips/stop_times are
unchanged from v2 — see the v2 doc for those tables.)

---

## 3. Deadhead & Block Management (revised)

**`block_pieces`** — updated to reference real locations:
- `id`, `block_id`, `sequence`, `piece_type`
  (`trip` / `deadhead` / `pull_out` / `pull_in`)
- `trip_id` (set when `piece_type = trip`; the piece's effective start/end
  location and time are derived from the trip's own `stop_times`, so
  they're not duplicated here)
- `from_location_id`, `to_location_id` (set for `deadhead` / `pull_out` /
  `pull_in` pieces — e.g. a `pull_out` typically goes *depot → first stop*,
  a `pull_in` goes *last stop → depot*, a `deadhead` goes *stop → stop*
  with no passengers)
- `start_time`, `end_time`

The block-consistency validator now checks actual location continuity
(piece N's end `location_id`/trip-end-stop should match piece N+1's start)
instead of fuzzy string matching, since everything's a real location now.

**BlockPiecesEditor** (frontend) becomes a location-aware builder: adding a
deadhead/pull-out/pull-in piece is a location picker (filtered to
depot/layover/stop as appropriate) rather than free text.

---

## 4. Full Rostering (new)

Once a board's trips are built into blocks, rostering is a separate
pass: assign blocks (or *pieces* of blocks — a driver doesn't have to take
a whole block) to actual drivers on actual dates, with breaks inserted.

**`duties`**
- `id`, `driver_id`, `date`, `schedule_version_id`, `notes`

**`duty_pieces`** — mirrors the `block_pieces` pattern, so a duty is built
the same way a block is: an ordered list of segments.
- `id`, `duty_id`, `sequence`, `piece_type`
  (`block_segment` / `break` / `sign_on` / `sign_off`)
- `block_id` (set for `block_segment`), `from_block_piece_sequence`,
  `to_block_piece_sequence` (which contiguous range of that block's pieces
  this duty covers — lets one block be split across two drivers, e.g. an
  AM driver and a PM driver, or a relief mid-shift)
- `location_id` (set for `break` / `sign_on` / `sign_off` — where the
  driver reports or takes the break; typically a depot or layover location)
- `start_time`, `end_time`

**Roster builder workflow (RosterPage):**
1. Pick a schedule board and date. See the day's blocks and their pieces
   (trip-by-trip) laid out on a timeline.
2. Create a duty, assign a driver.
3. Add `block_segment` pieces by selecting a block and dragging/entering
   the piece range it covers (defaults to the whole block if you don't
   split it).
4. Add `break` pieces between segments — the UI suggests break placement
   and flags it red/green against the minimum break parameter (§5) in
   real time as you build the duty.
5. On save, the roster service checks the whole duty against `parameters`
   (max driving time/day, min break) and flags violations without
   blocking save, so you can consciously override an edge case.

This gives you the actual "build a roster from finished timetables" step
you asked for, rather than just a data table.

---

## 5. Operating Parameters (replaces `roster_rules`)

**`parameters`** — a simple global key/value settings table, edited from a
new **SettingsPage**, rather than hardcoded config:
- `key`, `value`, `description`

Seed rows: `max_driving_minutes_per_day`, `min_break_minutes`,
`min_driving_minutes_before_break_required` (if you want "must take a
break after N continuous minutes" logic rather than just a flat daily
minimum), `max_duty_length_minutes`.

Kept as one flat table rather than per-driver/per-line overrides for now
— straightforward to add a scoped override table later (e.g.
`parameter_overrides` keyed by line or driver) if a single global rule set
turns out not to be granular enough once you're using it.

---

## 6. Fares — Confirmed, No Change

Your description (trip from zone A→A is rule 1, zone A→B is rule 2, etc.)
is exactly the `fare_rules(origin_zone_id, destination_zone_id, price)`
matrix already in the v2 design — same-zone trips are just the diagonal
of that matrix. No schema change needed here.

---

## 7. Updated Module List

- **`locations`** — CRUD for locations + location_attributes + stop_areas
  + location_transfers (replaces the old `network` module; covers stops,
  depots, layovers, and the walkable-connection graph between them).
- **`lines`** — CRUD for lines/patterns/pattern_stops + line_attributes.
- **`schedule_versions`** — unchanged from v2.
- **`schedule`** — unchanged from v2.
- **`fares`** — unchanged from v2.
- **`fleet`** — CRUD for vehicle_types/vehicles/blocks/block_pieces, now
  location-aware validation.
- **`roster`** — significantly expanded: duties/duty_pieces builder,
  validation against `parameters`.
- **`settings`** — NEW: CRUD for `parameters`.
- **`itinerary`** — search logic unchanged from v2, but its transfer edges
  now come from `stop_areas` + `location_transfers` (§1a) instead of the
  vaguer "precomputed walkable-pairs table" mentioned in v2 — same idea,
  now with a real, manageable data model behind it.
- **`pdf`** — unchanged from v2, plus duty cards now show real depot/
  layover names for sign-on/sign-off/break locations instead of free text.

---

## 8. Updated Frontend Pages

```
frontend/src/
  pages/
    LocationsPage.tsx       # renamed from NetworkPage; stops+depots+layovers, attributes editor, stop-areas & transfers panels, reference map
    LinesPage.tsx           # + line attributes editor
    BoardsPage.tsx
    SchedulePage.tsx
    FaresPage.tsx
    FleetPage.tsx            # blocks, now with location-aware BlockPiecesEditor
    RosterPage.tsx           # NEW workflow: build duties from blocks, insert breaks, live rule-check
    SettingsPage.tsx         # NEW: edit `parameters`
    ItineraryPage.tsx
  components/
    DataGrid.tsx
    MapView.tsx
    EntityForm.tsx
    AttributeEditor.tsx      # NEW: generic key/value editor, reused for locations and lines
    BlockPiecesEditor.tsx    # location-aware now
    DutyBuilder.tsx          # NEW: timeline-based duty assembly with break-rule feedback
```

---

## 9. Updated Build Phases

1. Scaffolding.
2. **Locations** — `locations` + `location_attributes` CRUD + LocationsPage.
3. **Lines** — lines/patterns/pattern_stops + `line_attributes` + LinesPage.
4. **Schedule boards** — as v2.
5. **Schedule within a board** — as v2.
6. **Fares** — as v2.
7. **PDF timetables** — as v2.
8. **Fleet & interlined blocks** — blocks/block_pieces with location-aware
   deadhead/pull-out/pull-in, BlockPiecesEditor.
9. **Settings** — `parameters` CRUD + SettingsPage (do this before roster,
   since rostering needs the rules to validate against).
10. **Full rostering** — duties/duty_pieces, DutyBuilder, PDF duty cards.
11. **Itinerary finder**.
12. **Polish** — CSV export, PDF styling.

---

## 10. Still Open

- Should `parameters` support per-line or per-driver overrides now, or is
  a single global rule set fine to start with (as drafted)?
- For `duty_pieces` splitting a block across two drivers: do you want the
  system to *require* a `break`/relief piece at the split point, or allow
  a direct hand-off with no gap (a mid-route driver swap)?
