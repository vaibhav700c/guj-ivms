import { useEffect, useState } from "react";
import { Search, Video, CircleDot, Copy, Check, Wifi, ArrowUpDown } from "lucide-react";
import { api } from "../lib/api";

interface Camera {
  id: number; external_id: string | null; name: string;
  city: string | null; district: string | null; camera_type: string | null;
  analytics_tier: string; status: string; health_score: number | null;
  resolution: string | null; stream_url: string | null;
  rtsp_url: string | null; whep_url: string | null;
  stream_protocol: string | null; vms_vendor: string | null;
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

export default function Cameras() {
  const [items, setItems] = useState<Camera[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [status, setStatus] = useState("");
  const [cities, setCities] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortAsc, setSortAsc] = useState(true);

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
            Sentinel Grid · {total} cameras · {online} online · {offline} offline
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
                <tr key={c.id} className={`table-row ${STATUS_ROW[c.status] ?? ""}`}>
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
                  <td className="table-cell">
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
    </div>
  );
}
