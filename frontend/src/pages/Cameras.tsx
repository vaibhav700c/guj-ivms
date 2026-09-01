import { useEffect, useState } from "react";
import { Search, Video, CircleDot, Copy, Check, Wifi, ArrowUpDown, X, Activity, Clock, Cpu } from "lucide-react";
import { api, formatDateTime } from "../lib/api";

interface Camera {
  id: number; external_id: string | null; name: string;
  city: string | null; district: string | null; camera_type: string | null;
  analytics_tier: string; status: string; health_score: number | null;
  resolution: string | null; stream_url: string | null;
  rtsp_url: string | null; whep_url: string | null;
  stream_protocol: string | null; vms_vendor: string | null;
  latitude: number; longitude: number; address: string | null;
  has_ir: boolean; has_ptz: boolean;
}

interface HealthLog {
  time: string; status: string; fps_actual: number | null;
  latency_ms: number | null; packet_loss: number | null; error_message: string | null;
}

interface AnprEvent {
  id: number; plate_text: string; vehicle_type: string | null;
  confidence: number; timestamp: string; direction: string | null;
}

const STATUS_BADGE: Record<string, string> = {
  online: "badge-online", offline: "badge-offline",
  maintenance: "badge-maintenance", unknown: "bg-slate-500/10 text-slate-400 badge",
};
const TIER_BADGE: Record<string, string> = {
  A: "bg-orange-500/15 text-orange-400 border border-orange-500/20 badge",
  B: "bg-cyan-500/15 text-cyan-400 border border-cyan-500/20 badge",
  C: "bg-slate-500/15 text-slate-400 border border-slate-500/20 badge",
};
const TIER_DESC: Record<string, string> = {
  A: "ANPR + Face + Detection (5–10 FPS)",
  B: "Detection + Tracking (2–5 FPS)",
  C: "Presence / Health (1 FPS)",
};
const STATUS_ROW: Record<string, string> = {
  offline: "bg-red-500/3", maintenance: "bg-amber-500/3",
};

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
  };
  return (
    <button onClick={copy} className="btn-icon w-6 h-6" title="Copy URL">
      {copied ? <Check size={10} className="text-emerald-400" /> : <Copy size={10} />}
    </button>
  );
}

type SortKey = "name" | "city" | "status" | "analytics_tier" | "health_score";

function CameraDrawer({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const [healthLog, setHealthLog] = useState<HealthLog[]>([]);
  const [anprEvents, setAnprEvents] = useState<AnprEvent[]>([]);
  const [loadingHealth, setLoadingHealth] = useState(true);

  useEffect(() => {
    setLoadingHealth(true);
    Promise.all([
      api<{ items: HealthLog[] }>(`/cameras/${camera.id}/health-log?limit=20`)
        .then((r) => setHealthLog(r.items)).catch(() => undefined),
      api<{ items: AnprEvent[] }>(`/analytics/anpr?camera_id=${camera.id}&hours=24&limit=10`)
        .then((r) => setAnprEvents(r.items)).catch(() => undefined),
    ]).finally(() => setLoadingHealth(false));
  }, [camera.id]);

  const lastHealth = healthLog[0];
  const uptime = healthLog.length
    ? Math.round((healthLog.filter((h) => h.status === "online").length / healthLog.length) * 100)
    : null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="w-full max-w-sm h-full bg-control-900 border-l border-control-800 flex flex-col overflow-hidden animate-slide-in-up shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 border-b border-control-800 flex items-start justify-between">
          <div>
            <div className="text-sm font-bold text-white">{camera.name}</div>
            <div className="text-[10px] font-mono text-slate-500 mt-0.5">{camera.external_id} · {camera.vms_vendor}</div>
          </div>
          <button onClick={onClose} className="btn-icon"><X size={14} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">

          {/* Status row */}
          <div className="flex flex-wrap gap-2">
            <span className={`${STATUS_BADGE[camera.status] ?? STATUS_BADGE.unknown} capitalize flex items-center gap-1`}>
              <CircleDot size={9} /> {camera.status}
            </span>
            <span className={TIER_BADGE[camera.analytics_tier] ?? TIER_BADGE.C} title={TIER_DESC[camera.analytics_tier]}>
              Tier {camera.analytics_tier}
            </span>
            {camera.has_ir && <span className="badge bg-violet-500/15 text-violet-400 border border-violet-500/20">IR</span>}
            {camera.has_ptz && <span className="badge bg-cyan-500/15 text-cyan-400 border border-cyan-500/20">PTZ</span>}
          </div>

          {/* Info grid */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            {[
              { label: "City", value: camera.city },
              { label: "District", value: camera.district },
              { label: "Type", value: camera.camera_type },
              { label: "Resolution", value: camera.resolution },
              { label: "Health Score", value: camera.health_score != null ? `${Math.round(camera.health_score * 100)}%` : "—" },
              { label: "Protocol", value: camera.stream_protocol },
            ].map(({ label, value }) => (
              <div key={label} className="bg-control-850 rounded-lg p-2 border border-control-800/50">
                <div className="text-[9px] text-slate-600 uppercase tracking-wider mb-0.5">{label}</div>
                <div className="text-slate-300 font-medium">{value ?? "—"}</div>
              </div>
            ))}
          </div>

          {/* Stream URLs */}
          {(camera.stream_url || camera.rtsp_url) && (
            <div className="space-y-1.5">
              <div className="text-[10px] text-slate-600 uppercase tracking-wider font-semibold">Stream URLs</div>
              {camera.stream_url && (
                <div className="flex items-center gap-2 bg-control-850 rounded-lg px-3 py-2 border border-control-800/50">
                  <Wifi size={10} className="text-emerald-400 shrink-0" />
                  <span className="font-mono text-[10px] text-emerald-400 truncate flex-1">{camera.stream_url}</span>
                  <CopyBtn text={camera.stream_url} />
                </div>
              )}
              {camera.rtsp_url && (
                <div className="flex items-center gap-2 bg-control-850 rounded-lg px-3 py-2 border border-control-800/50">
                  <Video size={10} className="text-cyan-400 shrink-0" />
                  <span className="font-mono text-[10px] text-cyan-400 truncate flex-1">{camera.rtsp_url}</span>
                  <CopyBtn text={camera.rtsp_url} />
                </div>
              )}
            </div>
          )}

          {/* Health log */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[10px] text-slate-600 uppercase tracking-wider font-semibold">
              <Activity size={10} /> Health Log (last 20 samples)
            </div>
            {loadingHealth ? (
              <div className="text-xs text-slate-600 py-2">Loading…</div>
            ) : healthLog.length === 0 ? (
              <div className="text-xs text-slate-600 py-2">No health data recorded yet.</div>
            ) : (
              <>
                {uptime !== null && (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-slate-500">Uptime:</span>
                    <div className="flex-1 h-1.5 bg-control-800 rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all"
                        style={{ width: `${uptime}%`, background: uptime > 80 ? "#10b981" : uptime > 50 ? "#f59e0b" : "#ef4444" }} />
                    </div>
                    <span className="font-mono text-slate-400">{uptime}%</span>
                  </div>
                )}
                {lastHealth && (
                  <div className="grid grid-cols-3 gap-1.5 text-center">
                    {[
                      { icon: Cpu, label: "FPS", value: lastHealth.fps_actual?.toFixed(1) ?? "—", color: "text-cyan-400" },
                      { icon: Clock, label: "Latency", value: lastHealth.latency_ms ? `${lastHealth.latency_ms}ms` : "—", color: "text-orange-400" },
                      { icon: Activity, label: "Loss", value: lastHealth.packet_loss ? `${(lastHealth.packet_loss * 100).toFixed(1)}%` : "0%", color: "text-violet-400" },
                    ].map(({ icon: Icon, label, value, color }) => (
                      <div key={label} className="bg-control-850 rounded-lg p-2 border border-control-800/50">
                        <Icon size={12} className={`mx-auto mb-1 ${color}`} />
                        <div className={`text-sm font-bold ${color}`}>{value}</div>
                        <div className="text-[9px] text-slate-600">{label}</div>
                      </div>
                    ))}
                  </div>
                )}
                <div className="space-y-0.5 max-h-32 overflow-y-auto">
                  {healthLog.map((h, i) => (
                    <div key={i} className="flex items-center gap-2 text-[10px] font-mono text-slate-500">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${h.status === "online" ? "bg-emerald-500" : "bg-red-500"}`} />
                      <span className="text-slate-600">{formatDateTime(h.time)}</span>
                      <span className="text-slate-500">{h.fps_actual != null ? `${h.fps_actual.toFixed(1)} fps` : ""}</span>
                      <span className="text-slate-700">{h.latency_ms != null ? `${h.latency_ms}ms` : ""}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Recent ANPR events */}
          {camera.analytics_tier === "A" || camera.analytics_tier === "B" ? (
            <div className="space-y-2">
              <div className="text-[10px] text-slate-600 uppercase tracking-wider font-semibold">Recent ANPR (24h)</div>
              {anprEvents.length === 0 ? (
                <div className="text-xs text-slate-600">No ANPR events in last 24h.</div>
              ) : (
                <div className="space-y-0.5 max-h-32 overflow-y-auto">
                  {anprEvents.map((e) => (
                    <div key={e.id} className="flex items-center gap-2 bg-control-850 rounded-lg px-2.5 py-1.5 border border-control-800/50">
                      <span className="font-mono text-xs text-orange-400 font-semibold">{e.plate_text}</span>
                      <span className="text-[10px] text-slate-600 ml-auto">{formatDateTime(e.timestamp)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}

        </div>
      </div>
    </div>
  );
}

export default function Cameras() {
  const [items, setItems] = useState<Camera[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [status, setStatus] = useState("");
  const [cities, setCities] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortAsc, setSortAsc] = useState(true);
  const [drawerCam, setDrawerCam] = useState<Camera | null>(null);

  useEffect(() => {
    api<{ by_city: Record<string, number> }>("/cameras/stats")
      .then((s) => setCities(Object.keys(s.by_city).sort()))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams({ limit: "500" });
    if (q) params.set("q", q);
    if (city) params.set("city", city);
    if (status) params.set("status", status);
    api<{ total: number; items: Camera[] }>(`/cameras?${params}`)
      .then((r) => { setItems(r.items); setTotal(r.total); })
      .catch(() => undefined);
  }, [q, city, status]);

  const sorted = [...items].sort((a, b) => {
    const aVal = a[sortKey] ?? ""; const bVal = b[sortKey] ?? "";
    if (aVal < bVal) return sortAsc ? -1 : 1;
    if (aVal > bVal) return sortAsc ? 1 : -1;
    return 0;
  });

  const sort = (key: SortKey) => {
    if (sortKey === key) setSortAsc((v) => !v);
    else { setSortKey(key); setSortAsc(true); }
  };

  const SortTh = ({ col, label }: { col: SortKey; label: string }) => (
    <th className="table-head cursor-pointer hover:text-slate-300 transition-colors select-none"
      onClick={() => sort(col)}>
      <div className="flex items-center gap-1">
        {label}
        <ArrowUpDown size={10} className={sortKey === col ? "text-orange-400" : "text-slate-700"} />
      </div>
    </th>
  );

  const online = items.filter((c) => c.status === "online").length;
  const offline = items.filter((c) => c.status === "offline").length;

  return (
    <div className="space-y-5 max-w-[1500px] animate-fade-in">

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Camera Registry</h1>
          <p className="page-subtitle">
            Sentinel Grid · {total} cameras · {online} online · {offline} offline · Click any row for details
          </p>
        </div>
        <div className="flex gap-2">
          {[
            { label: `${online} Online`, cls: "text-emerald-400 bg-emerald-500/10 border border-emerald-500/20" },
            { label: `${offline} Offline`, cls: "text-red-400 bg-red-500/10 border border-red-500/20" },
            { label: `${items.filter((c) => c.status === "maintenance").length} Maintenance`, cls: "text-amber-400 bg-amber-500/10 border border-amber-500/20" },
          ].map((s) => (
            <div key={s.label} className={`px-3 py-1.5 rounded-xl text-xs font-semibold ${s.cls}`}>{s.label}</div>
          ))}
        </div>
      </div>

      {/* Filters */}
      <div className="card p-4 flex flex-wrap gap-3 items-center">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search name, city, road…"
            value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className="input w-40" value={city} onChange={(e) => setCity(e.target.value)}>
          <option value="">All cities</option>
          {cities.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="input w-36" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="maintenance">Maintenance</option>
        </select>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px]">
            <thead>
              <tr className="border-b border-control-800 bg-control-850">
                <SortTh col="name" label="Camera" />
                <SortTh col="city" label="Location" />
                <th className="table-head">Type</th>
                <SortTh col="analytics_tier" label="Tier" />
                <th className="table-head">Stream URLs</th>
                <SortTh col="health_score" label="Health" />
                <SortTh col="status" label="Status" />
              </tr>
            </thead>
            <tbody className="divide-y divide-control-800/40">
              {sorted.map((c) => (
                <tr key={c.id}
                  className={`table-row cursor-pointer ${STATUS_ROW[c.status] ?? ""}`}
                  onClick={() => setDrawerCam(c)}>
                  <td className="table-cell">
                    <div className="flex items-center gap-2">
                      <div className={`w-1.5 h-6 rounded-full shrink-0 ${c.status === "online" ? "bg-emerald-500" : c.status === "offline" ? "bg-red-500" : "bg-amber-500"}`} />
                      <div>
                        <div className="font-semibold text-slate-200 text-sm">{c.name}</div>
                        <div className="text-[10px] font-mono text-slate-600">{c.external_id}</div>
                      </div>
                    </div>
                  </td>
                  <td className="table-cell">
                    <div className="text-sm text-slate-300">{c.city}</div>
                    <div className="text-[10px] text-slate-600">{c.district}</div>
                  </td>
                  <td className="table-cell">
                    <span className="text-xs text-slate-400 capitalize">{c.camera_type ?? "—"}</span>
                  </td>
                  <td className="table-cell">
                    <span className={TIER_BADGE[c.analytics_tier] ?? TIER_BADGE.C} title={TIER_DESC[c.analytics_tier]}>
                      Tier {c.analytics_tier}
                    </span>
                  </td>
                  <td className="table-cell" onClick={(e) => e.stopPropagation()}>
                    <div className="flex flex-col gap-1">
                      {c.stream_url && (
                        <div className="flex items-center gap-1">
                          <Wifi size={9} className="text-emerald-400" />
                          <span className="text-[10px] font-mono text-emerald-400">HLS</span>
                          <CopyBtn text={c.stream_url} />
                        </div>
                      )}
                      {c.rtsp_url && (
                        <div className="flex items-center gap-1">
                          <Video size={9} className="text-cyan-400" />
                          <span className="text-[10px] font-mono text-cyan-400">RTSP (TCP)</span>
                          <CopyBtn text={c.rtsp_url} />
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="table-cell">
                    <div className="flex items-center gap-2">
                      <div className="w-14 h-1.5 rounded-full bg-control-700 overflow-hidden">
                        <div className={`h-full rounded-full ${(c.health_score ?? 0) > 0.8 ? "bg-emerald-500" : (c.health_score ?? 0) > 0.5 ? "bg-amber-500" : "bg-red-500"}`}
                          style={{ width: `${Math.round((c.health_score ?? 0) * 100)}%` }} />
                      </div>
                      <span className="font-mono text-xs text-slate-500">
                        {c.health_score != null ? `${Math.round(c.health_score * 100)}%` : "—"}
                      </span>
                    </div>
                  </td>
                  <td className="table-cell">
                    <span className={`${STATUS_BADGE[c.status] ?? STATUS_BADGE.unknown} capitalize flex items-center gap-1`}>
                      <CircleDot size={9} /> {c.status}
                    </span>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7} className="table-cell text-center text-slate-600 py-12">
                    No cameras match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Camera detail drawer */}
      {drawerCam && <CameraDrawer camera={drawerCam} onClose={() => setDrawerCam(null)} />}
    </div>
  );
}
