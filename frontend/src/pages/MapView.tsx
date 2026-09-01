import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MapContainer, TileLayer, CircleMarker, Popup, Circle } from "react-leaflet";
import { Play, Layers, Radio, Eye, AlertTriangle, X, BarChart3 } from "lucide-react";
import { api } from "../lib/api";

interface Camera {
  id: number; external_id: string; name: string; city: string | null;
  district: string | null; status: string; analytics_tier: string;
  camera_type: string | null; latitude: number; longitude: number;
}
interface CoveragePoint {
  camera_id: number; name: string; lat: number; lng: number;
  status: string; analytics_tier: string; district: string | null; events: number;
}
interface DistrictGap {
  district: string; total: number; online: number; offline: number;
  tier_a: number; coverage_pct: number; gap_flags: string[]; is_gap: boolean;
}
interface GapAnalysis {
  districts: DistrictGap[]; gap_districts: DistrictGap[]; overall_coverage_pct: number;
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
  const [coveragePoints, setCoveragePoints] = useState<CoveragePoint[]>([]);
  const [heatmap, setHeatmap] = useState(false);
  const [gapData, setGapData] = useState<GapAnalysis | null>(null);
  const [showGap, setShowGap] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api<{ items: Camera[] }>("/cameras?limit=500").then((r) => setCameras(r.items)).catch(() => undefined);
  }, []);

  const loadCoverage = () => {
    if (coveragePoints.length > 0) { setHeatmap(!heatmap); return; }
    api<CoveragePoint[]>("/cameras/geo/coverage").then((pts) => {
      setCoveragePoints(pts);
      setHeatmap(true);
    }).catch(() => undefined);
  };

  const loadGapAnalysis = () => {
    if (gapData) { setShowGap(true); return; }
    api<GapAnalysis>("/cameras/gap-analysis").then((d) => {
      setGapData(d);
      setShowGap(true);
    }).catch(() => undefined);
  };

  const online = useMemo(() => cameras.filter((c) => c.status === "online").length, [cameras]);
  const tierA = useMemo(() => cameras.filter((c) => c.analytics_tier === "A").length, [cameras]);
  const color = (c: Camera) => colorBy === "status" ? STATUS_COLOR[c.status] ?? "#475569" : TIER_COLOR[c.analytics_tier] ?? "#475569";
  const radius = (c: Camera) => c.analytics_tier === "A" ? 8 : c.analytics_tier === "B" ? 7 : 5;

  // Heatmap: event density → radius + opacity
  const heatRadius = (events: number, max: number) => Math.max(1500, Math.min(6000, (events / max) * 6000));
  const maxEvents = Math.max(...coveragePoints.map((p) => p.events), 1);

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
        <div className="flex items-center gap-2 flex-wrap">
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
          <button onClick={loadCoverage} className={`btn-icon ${heatmap ? "text-orange-400 bg-orange-500/10 border-orange-500/25" : ""}`} title="Toggle ANPR density heatmap">
            <Layers size={14} />
          </button>
          <button onClick={loadGapAnalysis}
            className="btn-ghost text-xs flex items-center gap-1.5">
            <AlertTriangle size={13} /> Gap Analysis
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
            {/* Coverage zones */}
            {coverage && cameras.map((c) => (
              <Circle key={`cov-${c.id}`} center={[c.latitude, c.longitude]}
                radius={c.analytics_tier === "A" ? 3000 : 2000}
                pathOptions={{ color: color(c), weight: 0, fillOpacity: 0.07 }} />
            ))}
            {/* ANPR density heatmap */}
            {heatmap && coveragePoints.map((p) => (
              <Circle key={`heat-${p.camera_id}`} center={[p.lat, p.lng]}
                radius={heatRadius(p.events, maxEvents)}
                pathOptions={{
                  color: "#f97316",
                  weight: 0,
                  fillOpacity: Math.max(0.05, (p.events / maxEvents) * 0.45),
                }} />
            ))}
            {/* Camera markers */}
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
                    {/* ANPR density for this camera */}
                    {heatmap && (() => {
                      const pt = coveragePoints.find((p) => p.camera_id === c.id);
                      return pt ? (
                        <div className="text-[10px] text-orange-400 font-mono">{pt.events} ANPR events</div>
                      ) : null;
                    })()}
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
            {heatmap && (
              <div className="mt-3 pt-3 border-t border-control-800 space-y-1">
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <span className="w-3 h-3 rounded-full bg-orange-500/60 shrink-0" />
                  ANPR density heatmap
                </div>
                <div className="text-[10px] text-slate-600">Larger/brighter = more detections</div>
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
            <button onClick={loadGapAnalysis}
              className="mt-2 w-full btn-ghost text-xs justify-center flex items-center gap-1.5">
              <BarChart3 size={12} /> View Gap Analysis
            </button>
          </div>

          {/* Selected camera */}
          {selected && (
            <div className="card p-4 animate-slide-in-up">
              <div className="text-xs font-semibold text-slate-400 mb-2 flex items-center gap-1.5">
                <Eye size={11} /> Selected Camera
              </div>
              <div className="text-sm font-bold text-white mb-1">{selected.name}</div>
              <div className="text-xs text-slate-500 mb-1">{selected.city} · {selected.external_id}</div>
              <div className="flex gap-1 mb-3">
                <span className={`badge text-[10px] ${selected.status === "online" ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"}`}>
                  {selected.status}
                </span>
                <span className="badge text-[10px] bg-orange-500/15 text-orange-400">Tier {selected.analytics_tier}</span>
              </div>
              {selected.status === "online" && (
                <button onClick={() => navigate("/live")} className="btn-primary w-full text-xs justify-center">
                  <Play size={12} /> Open Live Stream
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Gap Analysis Modal */}
      {showGap && gapData && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowGap(false)}>
          <div className="bg-control-900 border border-control-800 rounded-2xl max-w-3xl w-full max-h-[80vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-control-800">
              <div>
                <div className="text-sm font-bold flex items-center gap-2">
                  <AlertTriangle size={14} className="text-amber-400" /> Gap Analysis Report
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  Overall coverage: {gapData.overall_coverage_pct}% · {gapData.gap_districts.length} districts with gaps
                </div>
              </div>
              <button onClick={() => setShowGap(false)} className="btn-icon">
                <X size={14} />
              </button>
            </div>
            <div className="overflow-y-auto flex-1">
              <table className="w-full">
                <thead className="sticky top-0 bg-control-850">
                  <tr className="border-b border-control-800">
                    {["District", "Total", "Online", "Offline", "Tier A", "Coverage", "Gaps"].map((h) => (
                      <th key={h} className="table-head">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-control-800/60">
                  {gapData.districts.map((d) => (
                    <tr key={d.district} className={`hover:bg-control-800/40 ${d.is_gap ? "row-high" : ""}`}>
                      <td className="table-cell font-semibold text-slate-200">{d.district}</td>
                      <td className="table-cell font-mono">{d.total}</td>
                      <td className="table-cell font-mono text-emerald-400">{d.online}</td>
                      <td className="table-cell font-mono text-red-400">{d.offline}</td>
                      <td className="table-cell font-mono text-orange-400">{d.tier_a}</td>
                      <td className="table-cell">
                        <div className="flex items-center gap-2">
                          <div className="w-20 h-1.5 bg-control-800 rounded-full overflow-hidden">
                            <div className="h-full rounded-full transition-all"
                              style={{
                                width: `${d.coverage_pct}%`,
                                background: d.coverage_pct >= 70 ? "#10b981" : d.coverage_pct >= 50 ? "#f59e0b" : "#ef4444",
                              }} />
                          </div>
                          <span className="text-xs font-mono text-slate-400">{d.coverage_pct}%</span>
                        </div>
                      </td>
                      <td className="table-cell">
                        <div className="flex flex-wrap gap-1">
                          {d.gap_flags.map((f) => (
                            <span key={f} className="badge text-[9px] bg-amber-500/10 text-amber-400 border border-amber-500/20">
                              {f.replace(/_/g, " ")}
                            </span>
                          ))}
                          {d.gap_flags.length === 0 && (
                            <span className="badge text-[9px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">OK</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
