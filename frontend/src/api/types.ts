export type Role = 'admin' | 'planner' | 'viewer'

export interface User {
  id: number
  username: string
  email?: string | null
  full_name?: string | null
  role: Role
  is_active: boolean
}

export interface AppConfig {
  app_name: string
  map_tile_url: string
  map_attribution: string
  map_default_lat: number
  map_default_lon: number
  map_default_zoom: number
}

export interface ValidationIssue {
  code: string
  severity: 'error' | 'warning' | 'info'
  message: string
  entity?: string | null
  entity_id?: number | null
  sequence?: number | null
}
export interface ValidationReport {
  ok: boolean
  issues: ValidationIssue[]
}

export interface Attribute {
  id?: number
  attribute_key: string
  attribute_value: string | null
}

export type LocationType = 'stop' | 'depot' | 'layover' | 'garage' | 'other'

export interface Location {
  id: number
  name: string
  code: string | null
  location_type: LocationType
  lat: number | null
  lon: number | null
  zone_id: number | null
  area_id: number | null
  is_active: boolean
  notes: string | null
  area_name?: string | null
  zone_name?: string | null
  attributes: Attribute[]
}

export interface StopArea {
  id: number
  name: string
  default_transfer_seconds: number
  notes: string | null
  location_ids: number[]
  location_names: string[]
}

export interface LocationTransfer {
  id: number
  from_location_id: number
  to_location_id: number
  walk_seconds: number
  distance_m: number | null
  is_bidirectional: boolean
  notes: string | null
  from_location_name?: string | null
  to_location_name?: string | null
}

export interface TransferEdge {
  from_location_id: number
  to_location_id: number
  walk_seconds: number
  source: 'stop_area' | 'explicit'
}

export interface Line {
  id: number
  short_name: string
  long_name: string | null
  description: string | null
  mode: string
  color: string | null
  text_color: string | null
  sort_order: number
  is_active: boolean
  attributes: Attribute[]
  pattern_count: number
}

export interface PatternStop {
  id?: number
  pattern_id?: number
  sequence: number
  location_id: number
  is_timepoint: boolean
  default_run_seconds: number
  default_dwell_seconds: number
  distance_from_start_m: number | null
  pickup_type: string
  drop_off_type: string
  location_name?: string | null
  location_code?: string | null
  lat?: number | null
  lon?: number | null
}

export interface Pattern {
  id: number
  line_id: number
  name: string
  direction: number
  headsign: string | null
  is_primary: boolean
  notes: string | null
  stop_count: number
  total_run_seconds: number
  stops: PatternStop[]
  attributes: Attribute[]
  /** Non-empty attribute values — what prints as bubbles, e.g. ["EXP"]. */
  badges: string[]
}

export interface ScheduleVersion {
  id: number
  name: string
  description: string | null
  start_date: string
  end_date: string
  status: 'draft' | 'active' | 'archived'
  trip_count: number
  block_count: number
}

export interface Calendar {
  id: number
  schedule_version_id: number
  name: string
  monday: boolean
  tuesday: boolean
  wednesday: boolean
  thursday: boolean
  friday: boolean
  saturday: boolean
  sunday: boolean
  start_date: string | null
  end_date: string | null
}

export interface StopTime {
  id: number
  trip_id: number
  pattern_stop_id: number
  arrival_seconds: string
  departure_seconds: string
  is_timepoint: boolean
  pickup_type: string
  drop_off_type: string
  sequence: number
  location_id: number | null
  location_name: string | null
}

/**
 * One of the pattern's stops, as a given trip treats it. `skipped` means the
 * trip has no stop time there — it runs past without calling.
 */
export interface TripCall {
  pattern_stop_id: number
  sequence: number
  location_id: number
  location_name: string | null
  is_timepoint: boolean
  skipped: boolean
  arrival_seconds: string | null
  departure_seconds: string | null
  pickup_type: string
  drop_off_type: string
}

export interface Trip {
  id: number
  schedule_version_id: number
  pattern_id: number
  calendar_id: number
  headsign: string | null
  short_name: string | null
  block_id: number | null
  vehicle_type_id: number | null
  wheelchair_accessible: boolean | null
  notes: string | null
  line_id: number | null
  line_short_name: string | null
  pattern_name: string | null
  calendar_name: string | null
  block_name: string | null
  start_seconds: string | null
  end_seconds: string | null
  stop_count: number
  stop_times?: StopTime[]
  calls?: TripCall[]
}

export interface TimetableColumn {
  trip_id: number
  pattern_id: number
  pattern_name: string | null
  line_short_name: string | null
  headsign: string | null
  badges: string[]
}

export interface Timetable {
  schedule_version_id: number
  schedule_version_name: string
  line_id: number
  line_short_name: string
  line_long_name: string | null
  pattern_id: number
  pattern_name: string
  /** Every pattern merged into this grid, in merge order. */
  pattern_ids: number[]
  pattern_names: string[]
  combined: boolean
  direction: number
  calendar_id: number | null
  calendar_name: string | null
  /** The trips on this page, left to right in departure order. */
  trip_ids: number[]
  columns: TimetableColumn[]
  rows: {
    pattern_stop_id: number
    sequence: number
    location_id: number
    location_name: string
    is_timepoint: boolean
    /** Only some of the combined patterns serve this stop. */
    partial: boolean
    cells: { trip_id: number; departure_seconds: string | null }[]
  }[]
  /** Unpaged count, so a slice is never mistaken for the whole thing. */
  total_trips: number
  limit: number | null
  offset: number
}

export interface FareZone {
  id: number
  name: string
  code: string | null
  description: string | null
  location_count: number
}

export interface FareMatrix {
  zone_ids: number[]
  zone_names: string[]
  cells: {
    origin_zone_id: number
    destination_zone_id: number
    rule_id: number | null
    price_cents: number | null
    currency: string | null
  }[]
  missing_count: number
}

export interface VehicleType {
  id: number
  name: string
  code: string | null
  capacity_seated: number | null
  capacity_standing: number | null
  fuel_type: string | null
  length_m: number | null
  wheelchair_accessible: boolean
  notes: string | null
}

export interface Vehicle {
  id: number
  fleet_number: string
  vehicle_type_id: number
  depot_location_id: number | null
  registration: string | null
  is_active: boolean
  notes: string | null
  vehicle_type_name: string | null
  depot_name: string | null
}

export type BlockPieceType = 'trip' | 'deadhead' | 'pull_out' | 'pull_in'

export interface BlockPiece {
  id?: number
  block_id?: number
  sequence: number
  piece_type: BlockPieceType
  trip_id: number | null
  from_location_id: number | null
  to_location_id: number | null
  start_seconds: string | null
  end_seconds: string | null
  notes: string | null
  effective_from_location_id?: number | null
  effective_to_location_id?: number | null
  effective_from_location_name?: string | null
  effective_to_location_name?: string | null
  effective_start_seconds?: string | null
  effective_end_seconds?: string | null
  trip_label?: string | null
  line_short_name?: string | null
}

export interface Block {
  id: number
  schedule_version_id: number
  name: string
  vehicle_id: number | null
  vehicle_type_id: number | null
  notes: string | null
  vehicle_fleet_number: string | null
  piece_count: number
  start_seconds: string | null
  end_seconds: string | null
  pieces?: BlockPiece[]
}

export interface UnassignedTrip {
  trip_id: number
  line_short_name: string | null
  headsign: string | null
  direction: number
  pattern_id: number | null
  from_location_id: number | null
  from_location_name: string | null
  to_location_id: number | null
  to_location_name: string | null
  start_seconds: string | null
  end_seconds: string | null
}

export interface Driver {
  id: number
  code: string
  first_name: string
  last_name: string
  email: string | null
  phone: string | null
  base_location_id: number | null
  is_active: boolean
  notes: string | null
  display_name: string
  base_location_name: string | null
}

export type DutyPieceType = 'block_segment' | 'break' | 'sign_on' | 'sign_off'

export interface DutyPiece {
  id?: number
  duty_id?: number
  sequence: number
  piece_type: DutyPieceType
  block_id: number | null
  from_block_piece_sequence: number | null
  to_block_piece_sequence: number | null
  location_id: number | null
  start_seconds: string | null
  end_seconds: string | null
  notes: string | null
  block_name?: string | null
  location_name?: string | null
  effective_start_seconds?: string | null
  effective_end_seconds?: string | null
  covers_piece_count?: number
}

export interface Duty {
  id: number
  name: string
  date: string
  schedule_version_id: number
  driver_id: number | null
  notes: string | null
  driver_name: string | null
  piece_count: number
  start_seconds: string | null
  end_seconds: string | null
  working_minutes: number
  driving_minutes: number
  break_minutes: number
  pieces?: DutyPiece[]
  validation?: ValidationReport | null
}

export interface BlockCoverage {
  block_id: number
  block_name: string
  total_pieces: number
  covered_sequences: number[]
  uncovered_sequences: number[]
  fully_covered: boolean
}

export interface ItineraryLeg {
  kind: 'ride' | 'walk'
  from_location_id: number
  from_location_name: string
  to_location_id: number
  to_location_name: string
  depart_seconds: string | null
  arrive_seconds: string | null
  duration_seconds: number
  trip_id: number | null
  line_id: number | null
  line_short_name: string | null
  headsign: string | null
  intermediate_stop_count: number
  transfer_source: string | null
}

export interface Itinerary {
  depart_seconds: string | null
  arrive_seconds: string | null
  duration_seconds: number
  transfer_count: number
  legs: ItineraryLeg[]
  fare_price_cents: number | null
  fare_currency: string | null
}

export interface ItineraryResponse {
  itineraries: Itinerary[]
}

export interface Parameter {
  key: string
  value: string
  value_type: 'int' | 'float' | 'bool' | 'string'
  description: string | null
  unit: string | null
  /** 'identity' = who this instance is; 'operating' = the roster rules. */
  category: string
}
