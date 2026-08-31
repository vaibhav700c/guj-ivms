import { useEffect, useState } from "react";
import { Search, Video, CircleDot, ExternalLink, Wifi } from "lucide-react";
import { api } from "../lib/api";

interface Camera {
  id: number;
  external_id: string | null;
  name: string;
  city: string | null;
  district: string | null;
  camera_type: string | null;
  analytics_tier: string;
  status: string;
  health_score: number | null;
  resolution: string | null;
  stream_url: string | null;      // HLS (CDN)
  rtsp_url: string | null;        // RTSP direct
  whep_url: string | null;        // WebRTC/WHEP
  stream_protocol: string | null;
  vms_vendor: string | null;
}

const STATUS_STYLE: Record<string, string> = {
  online: "bg-emerald-500/15 text-emerald-400",
  offline: "bg-red-500/15 text-red-400",
  maintenance: "bg-amber-500/15 text-amber-400",
  unknown: "bg-slate-500/15 text-slate-400",
};

const TIER_STYLE: Record<string, string> = {
  A: "bg-orange-500/15 text-orange-400",
  B: "bg-sky-500/15 text-sky-400",
  C: "bg-slate-500/15 text-slate-400",
};

const TIER_DESC: Record<string, string> = {
  A: "ANPR + Face + Detection (5-10 FPS)",
  B: "Detection + Tracking (2-5 FPS)",
  C: "Presence monitoring (1 FPS)",
};

export default function Cameras() {
  const [items, setItems] = useState<Camera[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [status, setStatus] = useState("");
  const [cities, setCities] = useState<string[]>([]);

  useEffect(() => {
    api<{ by_city: Record<string, number> }>("/cameras/stats")
      .then((s) => setCities(Object.keys(s.by_city).sort()))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (city) params.set("city", city);
    if (status) params.set("status", status);
    api<{ total: number; items: Camera[] }>(`/cameras?${params}`)
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
      })
      .catch(() => undefined);
  }, [q, city, status]);

  return (
    <div className="space-y-4 max-w-[1400px]">
      <div>
        <h1 className="text-xl font-bold">Camera Registry</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          Model 1 foundation — every camera catalogued and geolocated · {total} registered
        </p>
      </div>

      <div className="card p-4 flex flex-wrap gap-3 items-center">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-8" placeholder="Search name, city, road…"
            value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className="input w-44" value={city} onChange={(e) => setCity(e.target.value)}>
          <option value="">All cities</option>
          {cities.map((c) => (<option key={c} value={c}>{c}</option>))}
        </select>
        <select className="input w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="maintenance">Maintenance</option>
        </select>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px]">
            <thead>
              <tr className="border-b border-control-800 bg-control-850">
                <th className="table-head">Camera</th>
                <th className="table-head">City / District</th>
                <th className="table-head">Type</th>
                <th className="table-head">Tier</th>
                <th className="table-head">Stream</th>
                <th className="table-head">Health</th>
                <th className="table-head">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-control-800/60">
              {items.map((c) => (
                <tr key={c.id} className="hover:bg-control-800/40">
                  <td className="table-cell">
                    <div className="flex items-center gap-2 font-medium text-slate-200">
                      <Video size={14} className="text-slate-500" />{c.name}
                    </div>
                  </td>
                  <td className="table-cell">{c.city}<span className="text-slate-500"> · {c.district}</span></td>
                  <td className="table-cell capitalize">{c.camera_type}</td>
                  <td className="table-cell">
                    <span className={`badge ${TIER_STYLE[c.analytics_tier]}`} title={TIER_DESC[c.analytics_tier]}>
                      Tier {c.analytics_tier}
                    </span>
                  </td>
                  <td className="table-cell">
                    {c.stream_url ? (
                      <div className="flex flex-col gap-0.5">
                        <a
                          href={c.stream_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-emerald-400 hover:underline text-[11px] font-mono flex items-center gap-1"
                          title={c.stream_url}
                        >
                          <Wifi size={10} /> HLS <ExternalLink size={9} />
                        </a>
                        {c.rtsp_url && (
                          <span className="text-sky-500/80 text-[10px] font-mono truncate max-w-[140px]" title={c.rtsp_url}>
                            RTSP (TCP)
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-[11px] text-slate-600">{c.stream_protocol ?? "—"}</span>
                    )}
                  </td>
                  <td className="table-cell">
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-1.5 rounded bg-control-700 overflow-hidden">
                        <div className={`h-full ${(c.health_score ?? 0) > 0.8 ? "bg-emerald-500" : (c.health_score ?? 0) > 0.5 ? "bg-amber-500" : "bg-red-500"}`}
                          style={{ width: `${Math.round((c.health_score ?? 0) * 100)}%` }} />
                      </div>
                      <span className="font-mono text-xs text-slate-400">
                        {c.health_score != null ? Math.round(c.health_score * 100) : "—"}%
                      </span>
                    </div>
                  </td>
                  <td className="table-cell">
                    <span className={`badge capitalize ${STATUS_STYLE[c.status]}`}>
                      <CircleDot size={10} className="mr-1" />{c.status}
                    </span>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td className="table-cell text-slate-500" colSpan={7}>No cameras match filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
