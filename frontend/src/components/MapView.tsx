import {
  CircleMarker,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from 'react-leaflet'
import { useEffect, useMemo, useState } from 'react'
import 'leaflet/dist/leaflet.css'
import { useApp } from '../state/AppContext'

/**
 * Leaflet renders each CircleMarker as an SVG node. A few thousand of them
 * makes panning unusable, and a whole network's stops is well past that, so
 * only what is actually in view is drawn — and even that is capped.
 */
const MAX_MARKERS = 750

export interface MapPoint {
  id: number
  name: string
  lat: number
  lon: number
  kind?: string
  subtitle?: string
}

// Colour by location type rather than by line, since this map's job is
// "where are my stops and depots", not "what does the network look like".
const COLOURS: Record<string, string> = {
  stop: '#1f4e79',
  depot: '#a3541a',
  layover: '#16794c',
  garage: '#6b3fa0',
  other: '#667085',
}

function FitBounds({ points }: { points: MapPoint[] }) {
  const map = useMap()
  useEffect(() => {
    if (points.length === 0) return
    if (points.length === 1) {
      map.setView([points[0].lat, points[0].lon], 15)
      return
    }
    map.fitBounds(
      points.map((p) => [p.lat, p.lon] as [number, number]),
      { padding: [28, 28], maxZoom: 16 },
    )
  }, [points, map])
  return null
}

interface Viewport {
  north: number
  south: number
  east: number
  west: number
}

function ViewportTracker({ onChange }: { onChange: (v: Viewport) => void }) {
  const map = useMapEvents({
    moveend: () => report(),
    zoomend: () => report(),
  })
  function report() {
    const bounds = map.getBounds()
    onChange({
      north: bounds.getNorth(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      west: bounds.getWest(),
    })
  }
  useEffect(() => {
    report()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return null
}

export function MapView({
  points,
  path,
  small,
  onSelect,
}: {
  points: MapPoint[]
  /** Optional ordered line drawn through the given points (a pattern). */
  path?: MapPoint[]
  small?: boolean
  onSelect?: (id: number) => void
}) {
  const { config } = useApp()
  const [viewport, setViewport] = useState<Viewport | null>(null)
  const centre: [number, number] = [
    config?.map_default_lat ?? 52.3676,
    config?.map_default_lon ?? 4.9041,
  ]
  const plotted = useMemo(
    () => points.filter((p) => p.lat != null && p.lon != null),
    [points],
  )

  // Memoised deliberately: FitBounds runs an effect keyed on this array, and
  // fitting the map fires `moveend`, which sets viewport state and re-renders.
  // A fresh array each render would make those two chase each other forever.
  const fitTarget = useMemo(
    () => (path && path.length ? path : plotted.slice(0, MAX_MARKERS)),
    [path, plotted],
  )

  const visible = useMemo(() => {
    if (!viewport) return plotted.slice(0, MAX_MARKERS)
    return plotted.filter(
      (p) =>
        p.lat <= viewport.north &&
        p.lat >= viewport.south &&
        p.lon <= viewport.east &&
        p.lon >= viewport.west,
    )
  }, [plotted, viewport])

  const drawn = visible.slice(0, MAX_MARKERS)
  const hidden = plotted.length - drawn.length

  return (
    <div className="map-shell">
      <MapContainer
        center={centre}
        zoom={config?.map_default_zoom ?? 12}
        className={small ? 'map map-small' : 'map'}
        scrollWheelZoom
        preferCanvas
      >
      <TileLayer
        url={config?.map_tile_url ?? 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'}
        attribution={config?.map_attribution ?? '&copy; OpenStreetMap contributors'}
      />
      <FitBounds points={fitTarget} />
      <ViewportTracker onChange={setViewport} />
      {path && path.length > 1 && (
        <Polyline
          positions={path.map((p) => [p.lat, p.lon] as [number, number])}
          pathOptions={{ color: '#1f4e79', weight: 3, opacity: 0.7 }}
        />
      )}
      {drawn.map((point) => (
        <CircleMarker
          key={point.id}
          center={[point.lat, point.lon]}
          radius={point.kind === 'stop' || !point.kind ? 6 : 8}
          pathOptions={{
            color: COLOURS[point.kind ?? 'stop'] ?? COLOURS.other,
            fillColor: COLOURS[point.kind ?? 'stop'] ?? COLOURS.other,
            fillOpacity: 0.75,
            weight: 2,
          }}
          eventHandlers={onSelect ? { click: () => onSelect(point.id) } : undefined}
        >
          <Popup>
            <strong>{point.name}</strong>
            {point.subtitle && (
              <>
                <br />
                <span className="muted">{point.subtitle}</span>
              </>
            )}
          </Popup>
        </CircleMarker>
      ))}
      </MapContainer>
      {hidden > 0 && (
        <div className="map-note">
          Showing {drawn.length.toLocaleString()} of {plotted.length.toLocaleString()} —
          zoom in to see the rest.
        </div>
      )}
    </div>
  )
}
