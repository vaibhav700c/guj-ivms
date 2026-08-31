import { useEffect, useRef, useState } from "react";
import { Siren, CheckCheck, XCircle, BellOff } from "lucide-react";
import { api, wsUrl, formatDateTime } from "../lib/api";

interface AlertItem {
  id: number;
  alert_type: string;
  severity: string;
  camera_name: string | null;
  detected_identifier: string | null;
  match_confidence: number | null;
  message: string | null;
  status: string;
  timestamp: string;
}

const SEV_STYLE: Record<string, string> = {
  critical: "bg-red-500/15 text-red-400 border-red-500/40",
  high: "bg-orange-500/15 text-orange-400 border-orange-500/40",
  medium: "bg-amber-500/15 text-amber-400 border-amber-500/40",
  low: "bg-slate-500/15 text-slate-400 border-slate-500/40",
};

const STATUS_STYLE: Record<string, string> = {
  new: "bg-red-500/20 text-red-300 animate-pulse",
  acknowledged: "bg-amber-500/20 text-amber-300",
  resolved: "bg-emerald-500/15 text-emerald-300",
  false_positive: "bg-slate-500/20 text-slate-400",
};

export default function Alerts() {
  const [items, setItems] = useState<AlertItem[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [soundOn, setSoundOn] = useState(true);
  const [live, setLive] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const audioRef = useRef<AudioContext | null>(null);

  const load = () => {
    const qs = statusFilter ? `?status=${statusFilter}&limit=150` : "?limit=150";
    api<{ items: AlertItem[] }>(`/alerts${qs}`).then((r) => setItems(r.items)).catch(() => undefined);
  };
  useEffect(load, [statusFilter]);

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;
      ws.onopen = () => setLive(true);
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === "alert" && data.payload?.id) {
            setItems((prev) => [data.payload as AlertItem, ...prev].slice(0, 200));
            if (soundOn) {
              try {
                audioRef.current = audioRef.current || new AudioContext();
                const ctx = audioRef.current;
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.connect(gain); gain.connect(ctx.destination);
                osc.frequency.value = 880; gain.gain.value = 0.06;
                osc.start(); osc.stop(ctx.currentTime + 0.18);
              } catch { /* autoplay blocked */ }
            }
          }
        } catch { /* ignore */ }
      };
      ws.onclose = () => {
        setLive(false);
        setTimeout(connect, 3000);
      };
    };
    connect();
    return () => wsRef.current?.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soundOn]);

  const setStatus = async (id: number, status: string) => {
    await api(`/alerts/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
    setItems((prev) => prev.map((a) => (a.id === id ? { ...a, status } : a)));
  };

  return (
    <div className="space-y-4 max-w-[1000px]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            Live Alerts
            <span className={`badge ${live ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"}`}>
              {live ? "LIVE" : "OFFLINE"}
            </span>
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            WebSocket push from the watchlist correlation engine
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select className="input w-40" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            <option value="new">New</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
            <option value="false_positive">False Positive</option>
          </select>
          <button className={`btn ${soundOn ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setSoundOn(!soundOn)} title="Toggle alert sound">
            <Siren size={14} /> {soundOn ? "Sound On" : "Muted"}
          </button>
        </div>
      </div>

      <div className="space-y-2">
        {items.map((a) => (
          <div key={a.id} className={`card p-3 flex items-start gap-3 border ${SEV_STYLE[a.severity] ?? SEV_STYLE.low}`}>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`badge capitalize ${STATUS_STYLE[a.status] ?? ""}`}>{a.status}</span>
                <span className="badge bg-control-800 text-slate-300">{a.severity}</span>
                <span className="font-mono text-sm text-slate-100">{a.detected_identifier}</span>
                {a.match_confidence != null && (
                  <span className="text-[10px] font-mono text-slate-500">
                    conf {(a.match_confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>
              <div className="text-xs text-slate-400 mt-1">{a.message}</div>
              <div className="text-[10px] text-slate-600 font-mono mt-0.5">
                {a.camera_name} · {formatDateTime(a.timestamp)} · #{a.id}
              </div>
            </div>
            <div className="flex flex-col gap-1">
              {a.status === "new" && (
                <button className="btn-ghost text-[11px] px-2 py-1" onClick={() => setStatus(a.id, "acknowledged")}>
                  <CheckCheck size={12} /> Ack
                </button>
              )}
              {(a.status === "new" || a.status === "acknowledged") && (
                <>
                  <button className="btn-ghost text-[11px] px-2 py-1 text-emerald-400" onClick={() => setStatus(a.id, "resolved")}>
                    Resolve
                  </button>
                  <button className="btn-ghost text-[11px] px-2 py-1" onClick={() => setStatus(a.id, "false_positive")}>
                    <XCircle size={12} /> FP
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
        {items.length === 0 && (
          <div className="card p-10 text-center flex flex-col items-center gap-2 text-slate-500">
            <BellOff size={28} className="text-slate-600" />
            No alerts {statusFilter ? `with status “${statusFilter}”` : "yet"}. The simulator generates watchlist hits every few seconds.
          </div>
        )}
      </div>
    </div>
  );
}
