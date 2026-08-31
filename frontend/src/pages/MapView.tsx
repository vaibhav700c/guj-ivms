import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup, Circle, Tooltip } from "react-leaflet";
import { api } from "../lib/api";

interface Camera {
  id: number;
  name: string;
  city: string | null;
  status: string;
  analytics_tier: string;
  camera_type: string | null;
  latitude: number;
  longitude: number;
}

const STATUS_COLOR: Record<string, string> = {
  online: "#10b981",
  offline: "#ef4444",
  maintenance: "#f59e0b",
  unknown: "#64748b",
};

const TIER_COLOR: Record<string, string> = {
  A: "#f97316",
  B: "#0ea5e9",
  C: "#64748b",
};

export default function MapView() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [colorBy, setColorBy] = useState<"status" | "tier">("status");
  const [coverage, setCoverage] = useState(true);

  useEffect(() => {
    api<{ items: Camera[] }>("/cameras?limit=500").then((r) => setCameras(r.items)).catch(() => undefined);
  }, []);

  const online = useMemo(() => cameras.filter((c) => c.status === "online").length, [cameras]);
  const color = (c: Camera) => (colorBy === "status" ? STATUS_COLOR[c.status] : TIER_COLOR[c.analytics_tier]);

  return (
    <div className="space-y-4 max-w-[1400px]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">GIS Coverage Map</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {cameras.length} cameras plotted · {online} online · Gujarat state-wide grid
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className={`btn ${colorBy === "status" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setColorBy("status")}>By Status</button>
          <button className={`btn ${colorBy === "tier" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setColorBy("tier")}>By Tier</button>
          <button className={`btn ${coverage ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setCoverage(!coverage)}>Coverage Zones</button>
        </div>
      </div>

      <div className="card overflow-hidden">
        <MapContainer center={[22.6, 71.8]} zoom={7} className="h-[600px] w-full">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {coverage && cameras.map((c) => (
            <Circle key={`cov-${c.id}`} center={[c.latitude, c.longitude]} radius={2500}
              pathOptions={{ color: color(c), weight: 0.5, fillOpacity: 0.07 }} />
          ))}
          {cameras.map((c) => (
            <CircleMarker key={c.id} center={[c.latitude, c.longitude]} radius={6}
              pathOptions={{ color: color(c), fillColor: color(c), fillOpacity: 0.9, weight: 1.5 }}>
              <Tooltip direction="top" offset={[0, -6]}>
                <span className="text-xs">{c.name}</span>
              </Tooltip>
              <Popup>
                <div className="text-xs space-y-1">
                  <div className="font-semibold text-sm">{c.name}</div>
                  <div>{c.city} · {c.camera_type}</div>
                  <div>Analytics Tier {c.analytics_tier} · status {c.status}</div>
                  <div className="font-mono text-[10px]">{c.latitude.toFixed(5)}, {c.longitude.toFixed(5)}</div>
                </div>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>

      <div className="flex items-center gap-5 text-xs text-slate-400">
        {colorBy === "status" ? (
          <>
            <Legend color="#10b981" label="Online" />
            <Legend color="#ef4444" label="Offline" />
            <Legend color="#f59e0b" label="Maintenance" />
            <Legend color="#64748b" label="Unknown" />
          </>
        ) : (
          <>
            <Legend color="#f97316" label="Tier A — ANPR+Face" />
            <Legend color="#0ea5e9" label="Tier B — Detection+Tracking" />
            <Legend color="#64748b" label="Tier C — Presence" />
          </>
        )}
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
