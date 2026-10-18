import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useMemo } from "react";
import { MapContainer, Marker, TileLayer, Tooltip, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import "react-leaflet-cluster/dist/assets/MarkerCluster.css";
import "react-leaflet-cluster/dist/assets/MarkerCluster.Default.css";
import { severityColor } from "@/components/ui/badges";
import { useI18n } from "@/lib/i18n";
import { incidentTitle, reportCount } from "@/lib/store";
import type { Incident } from "@/types";

const DEMO_CENTER: [number, number] = [13.04, 80.21]; // Chennai
const iconCache = new Map<string, L.DivIcon>();

function pinIcon(severity: number, selected: boolean): L.DivIcon {
  const key = `${severity}-${selected}`;
  let icon = iconCache.get(key);
  if (!icon) {
    const size = selected ? 32 : 24;
    icon = L.divIcon({
      className: "",
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
      html: `<div style="width:${size}px;height:${size}px;border-radius:9999px;background:${severityColor(severity)};border:${selected ? 3 : 2}px solid #fff;box-shadow:0 0 0 ${selected ? 6 : 4}px color-mix(in srgb, ${severityColor(severity)} 30%, transparent),0 4px 10px rgba(0,0,0,.25);display:flex;align-items:center;justify-content:center;font:700 11px ui-monospace,monospace;color:#fff">${severity}</div>`,
    });
    iconCache.set(key, icon);
  }
  return icon;
}

/** The part of Leaflet.markercluster's cluster object we use (its types are not bundled). */
interface MarkerCluster {
  getAllChildMarkers(): L.Marker[];
}

function clusterIcon(cluster: MarkerCluster): L.DivIcon {
  const markers = cluster.getAllChildMarkers();
  const severity = Math.max(...markers.map((m) => Number(m.options.alt?.charAt(0)) || 1));
  const size = markers.length >= 10 ? 46 : 38;
  return L.divIcon({
    className: "",
    iconSize: [size, size],
    html: `<div style="width:${size}px;height:${size}px;border-radius:9999px;background:${severityColor(severity)};border:3px solid #fff;box-shadow:0 0 0 6px color-mix(in srgb, ${severityColor(severity)} 25%, transparent);display:flex;align-items:center;justify-content:center;font:700 13px ui-monospace,monospace;color:#fff">${markers.length}</div>`,
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

export function MapView({
  incidents,
  selectedId,
  onSelect,
}: {
  incidents: Incident[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { t } = useI18n();
  const located = useMemo(() => incidents.filter((i) => i.lat != null && i.lng != null), [incidents]);
  const selected = incidents.find((i) => i.id === selectedId);
  return (
    <MapContainer center={DEMO_CENTER} zoom={11} className="h-full w-full" preferCanvas>
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
            alt={`${incident.severity}: ${incidentTitle(incident, t)}`}
            eventHandlers={{ click: () => onSelect(incident.id) }}
          >
            <Tooltip direction="top" offset={[0, -12]}>
              {incidentTitle(incident, t)} · {reportCount(incident.report_count, t)}
            </Tooltip>
          </Marker>
        ))}
      </MarkerClusterGroup>
      <FlyTo incident={selected} />
    </MapContainer>
  );
}
