import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MapContainer, TileLayer, CircleMarker, Popup, Circle } from "react-leaflet";
import { Play, Layers, Radio, Eye } from "lucide-react";
import { api } from "../lib/api";

interface Camera {
  id: number; external_id: string; name: string; city: string | null;
  district: string | null; status: string; analytics_tier: string;
  camera_type: string | null; latitude: number; longitude: number;
}

const STATUS_COLOR: Record<string, string> = {
  online: "#10b981", offline: "#ef4444", maintenance: "#f59e0b", unknown: "#475569",
};
const TIER_COLOR: Record<string, string> = {
  A: "#f97316", B: "#06b6d4", C: "#475569",
};

export default function MapView() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [colorBy, setColorBy] = useState<"status" | "tier">("status");
  const [coverage, setCoverage] = useState(true);
  const [selected, setSelected] = useState<Camera | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api<{ items: Camera[] }>("/cameras?limit=500").then((r) => setCameras(r.items)).catch(() => undefined);
  }, []);

  const online = useMemo(() => cameras.filter((c) => c.status === "online").length, [cameras]);
  const tierA = useMemo(() => cameras.filter((c) => c.analytics_tier === "A").length, [cameras]);
  const color = (c: Camera) => colorBy === "status" ? STATUS_COLOR[c.status] ?? "#475569" : TIER_COLOR[c.analytics_tier] ?? "#475569";
  const radius = (c: Camera) => c.analytics_tier === "A" ? 8 : c.analytics_tier === "B" ? 7 : 5;

  return (
    <div className="space-y-4 max-w-[1500px] animate-fade-in">

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">GIS Coverage Map</h1>
          <p className="page-subtitle">
            {cameras.length} cameras · {online} online · {tierA} Tier A (ANPR+Face) · Gujarat state-wide
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1 p-1 bg-control-900 rounded-xl border border-control-800">
            <button onClick={() => setColorBy("status")}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${colorBy === "status" ? "bg-orange-500/15 text-orange-400 border border-orange-500/25" : "text-slate-500 hover:text-slate-300"}`}>
              By Status
            </button>
            <button onClick={() => setColorBy("tier")}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${colorBy === "tier" ? "bg-orange-500/15 text-orange-400 border border-orange-500/25" : "text-slate-500 hover:text-slate-300"}`}>
              By Tier
            </button>
          </div>
          <button onClick={() => setCoverage(!coverage)} className={`btn-icon ${coverage ? "text-cyan-400 bg-cyan-500/10 border-cyan-500/25" : ""}`} title="Toggle coverage zones">
            <Radio size={14} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">

        {/* Map */}
        <div className="lg:col-span-3 card overflow-hidden">
          <MapContainer center={[22.6, 71.8]} zoom={7} className="h-[580px] w-full">
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            />
            {coverage && cameras.map((c) => (
              <Circle key={`cov-${c.id}`} center={[c.latitude, c.longitude]}
                radius={c.analytics_tier === "A" ? 3000 : 2000}
                pathOptions={{ color: color(c), weight: 0, fillOpacity: 0.08 }} />
            ))}
            {cameras.map((c) => (
              <CircleMarker key={c.id} center={[c.latitude, c.longitude]}
                radius={radius(c)}
                pathOptions={{
                  color: "#000",
                  fillColor: color(c),
                  fillOpacity: c.status === "offline" ? 0.5 : 0.9,
                  weight: c === selected ? 2 : 0.5,
                }}
                eventHandlers={{ click: () => setSelected(c) }}>
                <Popup>
                  <div className="space-y-2 min-w-[160px]">
                    <div className="font-bold text-sm text-white">{c.name}</div>
                    <div className="flex gap-2 text-xs">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                        c.status === "online" ? "bg-emerald-500/20 text-emerald-300"
                          : c.status === "offline" ? "bg-red-500/20 text-red-300"
                          : "bg-amber-500/20 text-amber-300"
                      }`}>{c.status}</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-orange-500/15 text-orange-300">Tier {c.analytics_tier}</span>
                    </div>
                    <div className="text-xs text-slate-400">{c.city}{c.district ? ` · ${c.district}` : ""}</div>
                    <div className="text-[10px] font-mono text-slate-500">{c.camera_type} · {c.external_id}</div>
                    {c.status === "online" && (
                      <button
                        onClick={() => navigate("/live")}
                        className="w-full text-xs bg-orange-500/15 text-orange-400 border border-orange-500/25 rounded-lg py-1 flex items-center justify-center gap-1.5 hover:bg-orange-500/25 transition-colors">
                        <Play size={11} /> Open Live Stream
                      </button>
                    )}
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
        </div>

        {/* Side panel */}
        <div className="flex flex-col gap-3">

          {/* Legend */}
          <div className="card p-4">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 mb-3">
              <Layers size={12} /> Legend
            </div>
            {colorBy === "status" ? (
              <div className="space-y-2">
                {Object.entries({ Online: "#10b981", Offline: "#ef4444", Maintenance: "#f59e0b", Unknown: "#475569" }).map(([l, c]) => (
                  <div key={l} className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-xs text-slate-400">
                      <span className="w-3 h-3 rounded-full shrink-0" style={{ background: c }} />
                      {l}
                    </span>
                    <span className="text-xs font-mono text-slate-500">
                      {cameras.filter((cam) => cam.status === l.toLowerCase()).length}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {[
                  { tier: "A", desc: "ANPR + Face", color: "#f97316" },
                  { tier: "B", desc: "Detection + Track", color: "#06b6d4" },
                  { tier: "C", desc: "Presence", color: "#475569" },
                ].map((t) => (
                  <div key={t.tier} className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-xs text-slate-400">
                      <span className="w-3 h-3 rounded-full shrink-0" style={{ background: t.color }} />
                      Tier {t.tier} · {t.desc}
                    </span>
                    <span className="text-xs font-mono text-slate-500">
                      {cameras.filter((cam) => cam.analytics_tier === t.tier).length}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Stats */}
          <div className="card p-4 space-y-3">
            <div className="text-xs font-semibold text-slate-400">Grid Overview</div>
            {[
              { label: "Total cameras", value: cameras.length, color: "text-white" },
              { label: "Online", value: online, color: "text-emerald-400" },
              { label: "Offline", value: cameras.filter((c) => c.status === "offline").length, color: "text-red-400" },
              { label: "Maintenance", value: cameras.filter((c) => c.status === "maintenance").length, color: "text-amber-400" },
              { label: "Tier A (ANPR+Face)", value: cameras.filter((c) => c.analytics_tier === "A").length, color: "text-orange-400" },
            ].map((s) => (
              <div key={s.label} className="flex items-center justify-between text-xs">
                <span className="text-slate-500">{s.label}</span>
                <span className={`font-mono font-bold ${s.color}`}>{s.value}</span>
              </div>
            ))}
          </div>

          {/* Selected camera */}
          {selected && (
            <div className="card p-4 animate-slide-in-up">
              <div className="text-xs font-semibold text-slate-400 mb-2 flex items-center gap-1.5">
                <Eye size={11} /> Selected Camera
              </div>
              <div className="text-sm font-bold text-white mb-1">{selected.name}</div>
              <div className="text-xs text-slate-500 mb-3">{selected.city} · {selected.external_id}</div>
              {selected.status === "online" && (
                <button onClick={() => navigate("/live")} className="btn-primary w-full text-xs justify-center">
                  <Play size={12} /> Open Live Stream
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
