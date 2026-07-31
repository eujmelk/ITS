import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import { useEffect } from 'react'
import 'leaflet/dist/leaflet.css'
import { useApp } from '../state/AppContext'

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
  const centre: [number, number] = [
    config?.map_default_lat ?? 52.3676,
    config?.map_default_lon ?? 4.9041,
  ]
  const plotted = points.filter((p) => p.lat != null && p.lon != null)

  return (
    <MapContainer
      center={centre}
      zoom={config?.map_default_zoom ?? 12}
      className={small ? 'map map-small' : 'map'}
      scrollWheelZoom
    >
      <TileLayer
        url={config?.map_tile_url ?? 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'}
        attribution={config?.map_attribution ?? '&copy; OpenStreetMap contributors'}
      />
      <FitBounds points={plotted} />
      {path && path.length > 1 && (
        <Polyline
          positions={path.map((p) => [p.lat, p.lon] as [number, number])}
          pathOptions={{ color: '#1f4e79', weight: 3, opacity: 0.7 }}
        />
      )}
      {plotted.map((point) => (
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
  )
}
