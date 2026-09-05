import { useEffect, useRef, useState } from "react";
import { Search, Download, RefreshCw, Car, Filter } from "lucide-react";
import { api, describeApiError, formatDateTime } from "../lib/api";
import InlineError from "../components/InlineError";
import SimulatedBadge from "../components/SimulatedBadge";
import { useSettings } from "../store/settings";

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

interface AnprEvent {
  id: number;
  camera_id: number;
  camera_name: string | null;
  city: string | null;
  plate_text: string;
  plate_normalized: string;
  vehicle_type: string | null;
  vehicle_color: string | null;
  direction: string | null;
  confidence: number;
  ocr_confidence: number | null;
  snapshot_ref: string | null;
  timestamp: string;
  source?: string;
}

const TYPE_COLORS: Record<string, string> = {
  car: "text-cyan-400",
  motorcycle: "text-violet-400",
  truck: "text-orange-400",
  bus: "text-amber-400",
  auto: "text-emerald-400",
};

export default function AnprDetections() {
  const [items, setItems] = useState<AnprEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [plate, setPlate] = useState("");
  const [cameraId, setCameraId] = useState("");
  const [hours, setHours] = useState("24");
  const [loading, setLoading] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [liveMode, setLiveMode] = useState(true);
  const liveInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  const LIMIT = 50;
  const realOnly = useSettings((s) => s.realOnly);

  const load = async (reset = false) => {
    setLoading(true);
    const offset = reset ? 0 : page * LIMIT;
    const params = new URLSearchParams({
      limit: String(LIMIT),
      offset: String(offset),
      hours,
    });
    if (plate) params.set("plate", plate);
    if (cameraId) params.set("camera_id", cameraId);
    if (realOnly) params.set("source", "edge_worker");
    try {
      const r = await api<{ total: number; items: AnprEvent[] }>(`/analytics/anpr?${params}`);
      setTotal(r.total);
      if (reset) {
        setItems(r.items);
        setPage(0);
      } else {
        setItems(r.items);
      }
      setError(null);
    } catch (err) {
      // Keep whatever was last successfully loaded on screen — don't blank the
      // table on a transient failure, just surface the error alongside it.
      setError(describeApiError(err));
    } finally {
      setLoading(false);
      setLoadedOnce(true);
    }
  };

  useEffect(() => {
    load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plate, cameraId, hours, realOnly]);

  useEffect(() => {
    if (!liveMode) { if (liveInterval.current) clearInterval(liveInterval.current); return; }
    liveInterval.current = setInterval(() => load(true), 10_000);
    return () => { if (liveInterval.current) clearInterval(liveInterval.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveMode, plate, cameraId, hours, realOnly]);

  const confColor = (c: number) =>
    c >= 0.9 ? "text-emerald-400" : c >= 0.7 ? "text-amber-400" : "text-red-400";

  return (
    <div className="space-y-5 max-w-[1500px] animate-fade-in">

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-3">
            ANPR Detections
            {liveMode && (
              <span className="text-xs font-normal px-2 py-0.5 rounded-full border border-emerald-500/30 text-emerald-400 bg-emerald-500/10 animate-pulse">
                ● LIVE
              </span>
            )}
          </h1>
          <p className="page-subtitle">
            {total.toLocaleString("en-IN")} detections · plate reads from all Tier A/B cameras
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setLiveMode((v) => !v)}
            className={`btn-ghost text-xs ${liveMode ? "text-emerald-400 border-emerald-500/25 bg-emerald-500/10" : ""}`}>
            {liveMode ? "● Live (10s)" : "○ Live Off"}
          </button>
          <a
            href={`${BASE}/api/v1/reports/anpr.csv`}
            download
            className="btn-ghost text-xs flex items-center gap-1.5">
            <Download size={12} /> Export CSV
          </a>
        </div>
      </div>

      {error && (
        <InlineError message={error} onRetry={() => load(true)} onDismiss={() => setError(null)} />
      )}

      {/* Filters */}
      <div className="card p-4 flex flex-wrap gap-3 items-center">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            className="input pl-9 font-mono uppercase"
            placeholder="Search plate e.g. GJ01AB1234"
            value={plate}
            onChange={(e) => setPlate(e.target.value)}
          />
        </div>
        <div className="relative">
          <Filter size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            className="input pl-8 w-32"
            placeholder="Camera ID"
            type="number"
            value={cameraId}
            onChange={(e) => setCameraId(e.target.value)}
          />
        </div>
        <select className="input w-36" value={hours} onChange={(e) => setHours(e.target.value)}>
          <option value="1">Last 1 hour</option>
          <option value="6">Last 6 hours</option>
          <option value="12">Last 12 hours</option>
          <option value="24">Last 24 hours</option>
          <option value="48">Last 48 hours</option>
          <option value="168">Last 7 days</option>
        </select>
        <button onClick={() => load(true)} disabled={loading} className="btn-icon" title="Refresh">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
        {["car", "motorcycle", "truck", "bus", "auto", "other"].map((type) => {
          const count = items.filter((e) => (e.vehicle_type ?? "other") === type).length;
          return (
            <div key={type} className="bg-control-900 border border-control-800 rounded-xl p-2.5 text-center">
              <div className={`text-lg font-bold ${TYPE_COLORS[type] ?? "text-slate-400"}`}>{count}</div>
              <div className="text-[9px] text-slate-600 capitalize mt-0.5">{type}</div>
            </div>
          );
        })}
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px]">
            <thead>
              <tr className="border-b border-control-800 bg-control-850">
                <th className="table-head">Plate</th>
                <th className="table-head">Vehicle</th>
                <th className="table-head">Direction</th>
                <th className="table-head">Camera</th>
                <th className="table-head">City</th>
                <th className="table-head">Confidence</th>
                <th className="table-head">Timestamp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-control-800/40">
              {items.map((e) => (
                <tr key={e.id} className="table-row">
                  <td className="table-cell">
                    <div className="flex items-center gap-2">
                      <Car size={13} className={TYPE_COLORS[e.vehicle_type ?? ""] ?? "text-slate-500"} />
                      <span className="font-mono font-bold text-sm text-orange-400">{e.plate_text}</span>
                      {e.source === "simulator" && <SimulatedBadge />}
                    </div>
                    <div className="text-[9px] font-mono text-slate-700 ml-5">{e.plate_normalized}</div>
                  </td>
                  <td className="table-cell">
                    <span className={`badge text-[10px] capitalize ${TYPE_COLORS[e.vehicle_type ?? ""] ? `bg-current/10 ${TYPE_COLORS[e.vehicle_type ?? ""]}` : "bg-slate-500/10 text-slate-400"}`}>
                      {e.vehicle_type ?? "unknown"}
                    </span>
                    {e.vehicle_color && (
                      <div className="text-[10px] text-slate-600 mt-0.5">{e.vehicle_color}</div>
                    )}
                  </td>
                  <td className="table-cell">
                    <span className="text-xs text-slate-400 capitalize">{e.direction ?? "—"}</span>
                  </td>
                  <td className="table-cell">
                    <div className="text-xs text-slate-300">{e.camera_name ?? `cam #${e.camera_id}`}</div>
                    <div className="text-[9px] font-mono text-slate-600">ID:{e.camera_id}</div>
                  </td>
                  <td className="table-cell text-xs text-slate-400">{e.city ?? "—"}</td>
                  <td className="table-cell">
                    <span className={`font-mono text-xs font-semibold ${confColor(e.confidence)}`}>
                      {(e.confidence * 100).toFixed(1)}%
                    </span>
                    {e.ocr_confidence != null && (
                      <div className="text-[9px] font-mono text-slate-700">
                        OCR {(e.ocr_confidence * 100).toFixed(0)}%
                      </div>
                    )}
                  </td>
                  <td className="table-cell font-mono text-xs text-slate-500">
                    {formatDateTime(e.timestamp)}
                  </td>
                </tr>
              ))}
              {items.length === 0 && loading && !loadedOnce && (
                <tr>
                  <td colSpan={7} className="py-16 text-center">
                    <div className="flex flex-col items-center gap-2">
                      <RefreshCw size={18} className="animate-spin text-slate-600" />
                      <span className="text-xs text-slate-600">Loading detections…</span>
                    </div>
                  </td>
                </tr>
              )}
              {items.length === 0 && loadedOnce && !loading && !error && (
                <tr>
                  <td colSpan={7} className="py-16 text-center text-slate-600 text-sm">
                    No ANPR detections in the selected time range.
                  </td>
                </tr>
              )}
              {items.length === 0 && error && (
                <tr>
                  <td colSpan={7} className="py-16 text-center text-red-400/80 text-sm">
                    Could not load ANPR detections — see error above.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {total > LIMIT && (
          <div className="p-3 border-t border-control-800 flex items-center justify-between text-xs text-slate-500">
            <span>{Math.min((page + 1) * LIMIT, total)} of {total.toLocaleString("en-IN")}</span>
            <div className="flex gap-2">
              <button className="btn-ghost py-1 px-3 text-xs" disabled={page === 0} onClick={() => { setPage((p) => p - 1); load(); }}>
                ← Prev
              </button>
              <button className="btn-ghost py-1 px-3 text-xs" disabled={(page + 1) * LIMIT >= total} onClick={() => { setPage((p) => p + 1); load(); }}>
                Next →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
