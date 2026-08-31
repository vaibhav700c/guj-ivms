import { useEffect, useRef, useState } from "react";
import { Siren, CheckCheck, CheckCircle, XCircle, BellOff, Filter, RefreshCw } from "lucide-react";
import { api, wsUrl, formatDateTime } from "../lib/api";

interface AlertItem {
  id: number; alert_type: string; severity: string;
  camera_name: string | null; detected_identifier: string | null;
  match_confidence: number | null; message: string | null;
  status: string; timestamp: string;
}

const SEV_LEFT: Record<string, string> = {
  critical: "border-l-4 border-l-red-500",
  high:     "border-l-4 border-l-orange-500",
  medium:   "border-l-4 border-l-amber-500",
  low:      "border-l-4 border-l-slate-600",
};
const SEV_BADGE: Record<string, string> = {
  critical: "badge-critical", high: "badge-high",
  medium: "badge-medium", low: "badge-low",
};
const STATUS_BADGE: Record<string, string> = {
  new: "bg-red-500/20 text-red-300 border border-red-500/30 animate-pulse",
  acknowledged: "bg-amber-500/15 text-amber-300 border border-amber-500/25",
  resolved: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/25",
  false_positive: "bg-slate-500/15 text-slate-400 border border-slate-500/25",
};

const TABS = [
  { value: "", label: "All" },
  { value: "new", label: "New" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "resolved", label: "Resolved" },
  { value: "false_positive", label: "False Positive" },
];

export default function Alerts() {
  const [items, setItems] = useState<AlertItem[]>([]);
  const [tab, setTab] = useState("new");
  const [severityFilter, setSeverityFilter] = useState("");
  const [live, setLive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [actioning, setActioning] = useState<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const load = () => {
    setLoading(true);
    const qs = new URLSearchParams({ limit: "200" });
    if (tab) qs.set("status", tab);
    if (severityFilter) qs.set("severity", severityFilter);
    api<{ items: AlertItem[] }>(`/alerts?${qs}`)
      .then((r) => setItems(r.items))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  };
  useEffect(load, [tab, severityFilter]);

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;
      ws.onopen = () => setLive(true);
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === "alert" && data.payload?.id) {
            setItems((prev) => {
              const a = data.payload as AlertItem;
              if (tab === "" || a.status === tab) return [a, ...prev].slice(0, 200);
              return prev;
            });
          }
        } catch { /* ignore */ }
      };
      ws.onclose = () => { setLive(false); setTimeout(connect, 3000); };
    };
    connect();
    return () => wsRef.current?.close();
  }, [tab]);

  const setStatus = async (id: number, status: string) => {
    setActioning(id);
    try {
      await api(`/alerts/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
      setItems((prev) => prev.map((a) => (a.id === id ? { ...a, status } : a)));
      if (tab && tab !== status) setItems((prev) => prev.filter((a) => a.id !== id));
    } finally { setActioning(null); }
  };

  const counts = items.reduce((acc, a) => {
    acc[a.severity] = (acc[a.severity] || 0) + 1; return acc;
  }, {} as Record<string, number>);

  return (
    <div className="space-y-5 max-w-[1100px] animate-fade-in">

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-3">
            Live Alerts
            <span className={`text-xs font-normal px-2 py-0.5 rounded-full border ${live ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/10" : "border-red-500/30 text-red-400 bg-red-500/10"}`}>
              {live ? "● LIVE" : "○ RECONNECTING"}
            </span>
          </h1>
          <p className="page-subtitle">Correlation engine watchlist hits · auto-pushed via WebSocket</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            {["critical","high","medium"].map((s) => (
              <button key={s} onClick={() => setSeverityFilter(severityFilter === s ? "" : s)}
                className={`badge cursor-pointer transition-all ${severityFilter === s ? SEV_BADGE[s] : "bg-control-800 text-slate-500 border border-control-700"}`}>
                {s} {counts[s] ? `(${counts[s]})` : ""}
              </button>
            ))}
          </div>
          <button onClick={load} className="btn-icon" title="Refresh">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Severity summary strip */}
      {items.length > 0 && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { sev: "critical", label: "Critical", color: "text-red-400", bg: "bg-red-500/10 border-red-500/20" },
            { sev: "high",     label: "High",     color: "text-orange-400", bg: "bg-orange-500/10 border-orange-500/20" },
            { sev: "medium",   label: "Medium",   color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
            { sev: "low",      label: "Low",      color: "text-slate-400", bg: "bg-slate-500/10 border-slate-500/20" },
          ].map((s) => (
            <div key={s.sev} className={`rounded-xl border p-3 text-center cursor-pointer transition-all ${s.bg} ${severityFilter === s.sev ? "ring-1 ring-current ring-offset-1 ring-offset-control-950" : ""}`}
              onClick={() => setSeverityFilter(severityFilter === s.sev ? "" : s.sev)}>
              <div className={`text-2xl font-bold ${s.color}`}>{counts[s.sev] ?? 0}</div>
              <div className="text-xs text-slate-500 mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Status tabs */}
      <div className="flex gap-1 p-1 bg-control-900 rounded-xl border border-control-800 w-fit">
        {TABS.map((t) => (
          <button key={t.value}
            onClick={() => setTab(t.value)}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${tab === t.value ? "bg-orange-500/15 text-orange-400 border border-orange-500/25" : "text-slate-500 hover:text-slate-300"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Alert list */}
      <div className="space-y-2">
        {items
          .filter((a) => !severityFilter || a.severity === severityFilter)
          .map((a) => (
          <div key={a.id}
            className={`card p-0 overflow-hidden flex animate-slide-in-up ${SEV_LEFT[a.severity] ?? ""}`}>
            <div className="flex-1 p-4">
              <div className="flex items-center gap-2 flex-wrap mb-1.5">
                <span className={`badge text-[10px] ${STATUS_BADGE[a.status] ?? ""}`}>
                  {a.status.replace("_", " ").toUpperCase()}
                </span>
                <span className={`badge text-[10px] ${SEV_BADGE[a.severity] ?? SEV_BADGE.low}`}>
                  {a.severity.toUpperCase()}
                </span>
                {a.detected_identifier && (
                  <span className="font-mono text-sm font-semibold text-white">{a.detected_identifier}</span>
                )}
                {a.match_confidence != null && (
                  <span className="text-[10px] font-mono text-slate-500 ml-auto">
                    {(a.match_confidence * 100).toFixed(0)}% conf
                  </span>
                )}
              </div>
              <div className="text-sm text-slate-300 leading-snug">{a.message}</div>
              <div className="text-[10px] text-slate-600 font-mono mt-1.5 flex items-center gap-2">
                {a.camera_name && <span className="text-slate-500">{a.camera_name}</span>}
                {a.camera_name && <span>·</span>}
                <span>{formatDateTime(a.timestamp)}</span>
                <span>·</span>
                <span className="text-slate-700">#{a.id}</span>
              </div>
            </div>

            {/* Action buttons */}
            {(a.status === "new" || a.status === "acknowledged") && (
              <div className="flex flex-col border-l border-control-800 shrink-0">
                {a.status === "new" && (
                  <button
                    disabled={actioning === a.id}
                    onClick={() => setStatus(a.id, "acknowledged")}
                    className="flex-1 flex items-center justify-center gap-1.5 px-4 text-xs font-medium text-amber-400 hover:bg-amber-500/10 transition-colors border-b border-control-800 min-w-[90px]">
                    <CheckCheck size={13} /> Ack
                  </button>
                )}
                <button
                  disabled={actioning === a.id}
                  onClick={() => setStatus(a.id, "resolved")}
                  className="flex-1 flex items-center justify-center gap-1.5 px-4 text-xs font-medium text-emerald-400 hover:bg-emerald-500/10 transition-colors border-b border-control-800">
                  <CheckCircle size={13} /> Resolve
                </button>
                <button
                  disabled={actioning === a.id}
                  onClick={() => setStatus(a.id, "false_positive")}
                  className="flex-1 flex items-center justify-center gap-1.5 px-4 text-xs font-medium text-slate-400 hover:bg-control-800 transition-colors">
                  <XCircle size={12} /> FP
                </button>
              </div>
            )}
          </div>
        ))}

        {items.filter((a) => !severityFilter || a.severity === severityFilter).length === 0 && (
          <div className="card p-16 text-center flex flex-col items-center gap-3">
            <BellOff size={32} className="text-slate-700" />
            <div className="text-sm text-slate-500">
              No {tab || "active"} alerts{severityFilter ? ` at ${severityFilter} severity` : ""}
            </div>
            <div className="text-xs text-slate-600">
              The simulator generates watchlist hits every few seconds
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
