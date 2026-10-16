import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useMemo } from "react";
import { MapContainer, Marker, TileLayer, Tooltip, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import "react-leaflet-cluster/dist/assets/MarkerCluster.css";
import "react-leaflet-cluster/dist/assets/MarkerCluster.Default.css";
import type { Incident } from "../types";
import { SEVERITY_COLOR } from "./Badges";

const DEMO_CENTER: [number, number] = [28.5355, 77.391];

const iconCache = new Map<string, L.DivIcon>();

function pinIcon(severity: number, selected: boolean): L.DivIcon {
  const key = `${severity}-${selected}`;
  let icon = iconCache.get(key);
  if (!icon) {
    const size = selected ? 30 : 22;
    icon = L.divIcon({
      className: "",
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
      html: `<div style="width:${size}px;height:${size}px;border-radius:9999px;background:${SEVERITY_COLOR[severity]};border:2px solid ${selected ? "#fff" : "rgba(0,0,0,.55)"};box-shadow:0 0 0 4px ${SEVERITY_COLOR[severity]}33;display:flex;align-items:center;justify-content:center;font:700 11px ui-monospace,monospace;color:#000">${severity}</div>`,
    });
    iconCache.set(key, icon);
  }
  return icon;
}

/** The part of Leaflet.markercluster's cluster object we use (its types are not bundled). */
interface MarkerCluster {
  getAllChildMarkers(): L.Marker[];
}

/** Cluster bubble coloured by the most severe incident inside it. */
function clusterIcon(cluster: MarkerCluster): L.DivIcon {
  const markers = cluster.getAllChildMarkers();
  const severity = Math.max(...markers.map((m) => Number(m.options.alt?.charAt(0)) || 1));
  const size = markers.length >= 10 ? 44 : 36;
  return L.divIcon({
    className: "",
    iconSize: [size, size],
    html: `<div style="width:${size}px;height:${size}px;border-radius:9999px;background:${SEVERITY_COLOR[severity]}cc;border:3px solid ${SEVERITY_COLOR[severity]}55;display:flex;align-items:center;justify-content:center;font:700 13px ui-monospace,monospace;color:#000">${markers.length}</div>`,
  });
}

function FlyTo({ incident }: { incident: Incident | undefined }) {
  const map = useMap();
  useEffect(() => {
    if (incident?.lat != null && incident.lng != null) {
      map.flyTo([incident.lat, incident.lng], Math.max(map.getZoom(), 14), { duration: 0.6 });
    }
  }, [incident?.id, incident?.lat, incident?.lng, map]);
  return null;
}

interface MapViewProps {
  incidents: Incident[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function MapView({ incidents, selectedId, onSelect }: MapViewProps) {
  const located = useMemo(() => incidents.filter((i) => i.lat != null && i.lng != null), [incidents]);
  const selected = incidents.find((i) => i.id === selectedId);
  return (
    <MapContainer center={DEMO_CENTER} zoom={12} className="h-full w-full" preferCanvas>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <MarkerClusterGroup chunkedLoading maxClusterRadius={40} iconCreateFunction={clusterIcon}>
        {located.map((incident) => (
          <Marker
            key={incident.id}
            position={[incident.lat!, incident.lng!]}
            icon={pinIcon(incident.severity, incident.id === selectedId)}
            alt={`${incident.severity}: ${incident.title}`}
            eventHandlers={{ click: () => onSelect(incident.id) }}
          >
            <Tooltip direction="top" offset={[0, -10]}>
              {incident.title} · {incident.report_count} report{incident.report_count === 1 ? "" : "s"}
            </Tooltip>
          </Marker>
        ))}
      </MarkerClusterGroup>
      <FlyTo incident={selected} />
    </MapContainer>
  );
}
