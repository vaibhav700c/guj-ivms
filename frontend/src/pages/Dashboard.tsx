import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Video, Activity, Siren, Database, TrendingUp, Car,
  CircleAlert, Cpu, CheckCircle, AlertTriangle, ArrowRight,
  Play, Eye, PlayCircle, StopCircle, RefreshCw,
} from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from "recharts";
import { api, formatDateTime } from "../lib/api";

interface Overview {
  cameras_total: number; cameras_online: number; cameras_offline: number;
  cameras_maintenance: number; sentinel_cameras_total: number;
  anpr_events_24h: number; anpr_events_total: number;
  detections_24h: number; watchlist_active: number; registry_vehicles: number;
}
interface AlertItem { id: number; severity: string; message: string; status: string; timestamp: string; camera_name: string | null; }
interface AlertStats { by_status: Record<string, number>; by_severity: Record<string, number>; total: number; unacknowledged: number; }
interface TierItem { tier: string; count: number; description: string; }
interface SimStatus { running: boolean; events_generated: number; alerts_generated: number; }

const SEV: Record<string, string> = {
  critical: "badge-critical", high: "badge-high", medium: "badge-medium", low: "badge-low",
};

/* Animated number counter */
function AnimNum({ value, suffix = "" }: { value: number; suffix?: string }) {
  const [display, setDisplay] = useState(0);
  const prev = useRef(0);
  useEffect(() => {
    const start = prev.current;
    const end = value;
    const dur = 700;
    const t0 = performance.now();
    const step = (now: number) => {
      const frac = Math.min((now - t0) / dur, 1);
      const ease = 1 - Math.pow(1 - frac, 3);
      setDisplay(Math.round(start + (end - start) * ease));
      if (frac < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    prev.current = end;
  }, [value]);
  return <>{display.toLocaleString("en-IN")}{suffix}</>;
}

function StatCard({
  icon: Icon, label, value, sub, colorClass, glowColor, trend,
}: {
  icon: React.ElementType; label: string; value: number | string;
  sub?: string; colorClass: string; glowColor: string; trend?: string;
}) {
  return (
    <div className="stat-card group animate-slide-in-up" style={{ "--glow-color": glowColor } as React.CSSProperties}>
      <div className="flex items-start justify-between">
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${colorClass}`}>
          <Icon size={19} />
        </div>
        {trend && (
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-md bg-control-800 text-slate-400">{trend}</span>
        )}
      </div>
      <div className="mt-3">
        <div className="text-3xl font-bold tracking-tight text-white">
          {typeof value === "number" ? <AnimNum value={value} /> : value}
        </div>
        <div className="text-xs text-slate-400 mt-1 font-medium">{label}</div>
        {sub && <div className="text-[10px] text-slate-600 mt-0.5">{sub}</div>}
      </div>
    </div>
  );
}

const TT_STYLE = {
  background: "#0d1a2e", border: "1px solid #1e3352", borderRadius: 10, fontSize: 11, color: "#cbd5e1",
};

const TIER_META: Record<string, { color: string; label: string; desc: string }> = {
  A: { color: "#f97316", label: "Tier A", desc: "Full ANPR + Face" },
  B: { color: "#06b6d4", label: "Tier B", desc: "Detection + Track" },
  C: { color: "#475569", label: "Tier C", desc: "Presence / Health" },
};

export default function Dashboard() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [timeline, setTimeline] = useState<{ bucket: string; count: number }[]>([]);
  const [traffic, setTraffic] = useState<{ camera: string; city: string; events: number }[]>([]);
  const [simStatus, setSimStatus] = useState<SimStatus | null>(null);
  const [alertStats, setAlertStats] = useState<AlertStats | null>(null);
  const [tiers, setTiers] = useState<TierItem[]>([]);
  const [simLoading, setSimLoading] = useState(false);

  const refresh = () => {
    api<Overview>("/analytics/overview").then(setOv).catch(() => undefined);
    api<{ items: AlertItem[] }>("/alerts?limit=8&status=new").then((r) => setAlerts(r.items)).catch(() => undefined);
    api<{ bucket: string; count: number }[]>("/analytics/events/timeline?hours=12").then(setTimeline).catch(() => undefined);
    api<{ camera: string; city: string; events: number }[]>("/vehicles/traffic/by-camera?limit=6").then(setTraffic).catch(() => undefined);
    api<SimStatus>("/simulator/status").then(setSimStatus).catch(() => undefined);
    api<AlertStats>("/alerts/stats").then(setAlertStats).catch(() => undefined);
    api<TierItem[]>("/analytics/tiers/coverage").then(setTiers).catch(() => undefined);
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15_000);
    return () => clearInterval(id);
  }, []);

  const toggleSim = async () => {
    if (!simStatus) return;
    setSimLoading(true);
    try {
      if (simStatus.running) {
        await api("/simulator/stop", { method: "POST" });
      } else {
        await api("/simulator/start", { method: "POST" });
      }
      const s = await api<SimStatus>("/simulator/status");
      setSimStatus(s);
    } finally {
      setSimLoading(false);
    }
  };

  const onlinePct = ov ? Math.round((ov.cameras_online / Math.max(ov.cameras_total, 1)) * 100) : 0;
  const now = new Date();

  // Build tier display — real DB data, fallback to [] if not loaded yet
  const tierDisplay = ["A", "B", "C"].map((t) => {
    const found = tiers.find((x) => x.tier === t);
    const meta = TIER_META[t];
    return { ...meta, cameras: found?.count ?? "…" };
  });

  return (
    <div className="space-y-6 max-w-[1500px] animate-fade-in">

      {/* ── Page header ─────────────────────────────────────── */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Control Room Dashboard</h1>
          <p className="page-subtitle">
            Gujarat Integrated Video Management &amp; Analytics ·{" "}
            {now.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/live" className="btn-primary text-xs">
            <Play size={12} /> Live View
          </Link>
          <Link to="/alerts" className="btn-ghost text-xs">
            <Eye size={12} /> All Alerts
          </Link>
        </div>
      </div>

      {/* ── Alert stats strip ─────────────────────────────────────── */}
      {alertStats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "New / Unacknowledged", value: alertStats.by_status?.new ?? 0, color: "text-red-400", bg: "bg-red-500/10 border-red-500/20", icon: Siren },
            { label: "Acknowledged", value: alertStats.by_status?.acknowledged ?? 0, color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20", icon: CheckCircle },
            { label: "Resolved Today", value: alertStats.by_status?.resolved ?? 0, color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20", icon: CheckCircle },
            { label: "False Positives", value: alertStats.by_status?.false_positive ?? 0, color: "text-slate-400", bg: "bg-slate-500/10 border-slate-500/20", icon: AlertTriangle },
          ].map((s) => (
            <Link key={s.label} to="/alerts"
              className={`rounded-xl border p-3 flex items-center gap-3 transition-all hover:scale-[1.02] cursor-pointer ${s.bg}`}>
              <s.icon size={18} className={s.color} />
              <div>
                <div className={`text-xl font-bold ${s.color}`}>{s.value.toLocaleString("en-IN")}</div>
                <div className="text-[10px] text-slate-500 mt-0.5">{s.label}</div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* ── Stat row ─────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          icon={Video} label="Cameras Online"
          value={ov ? `${ov.cameras_online}/${ov.cameras_total}` : "—"}
          sub={`${onlinePct}% fleet availability · ${ov?.cameras_maintenance ?? 0} in maintenance`}
          colorClass="bg-emerald-500/15 text-emerald-400"
          glowColor="#10b98120"
          trend={`${onlinePct}%`}
        />
        <StatCard
          icon={Car} label="ANPR Events (24h)"
          value={ov?.anpr_events_24h ?? 0}
          sub={ov ? `${ov.anpr_events_total.toLocaleString("en-IN")} lifetime detections` : ""}
          colorClass="bg-cyan-500/15 text-cyan-400"
          glowColor="#06b6d420"
        />
        <StatCard
          icon={Siren} label="Active Watchlist"
          value={ov?.watchlist_active ?? 0}
          sub={`${ov?.registry_vehicles ?? 0} VAHAN-like registry records`}
          colorClass="bg-red-500/15 text-red-400"
          glowColor="#ef444420"
        />
        <StatCard
          icon={Activity} label="Detections (24h)"
          value={ov?.detections_24h ?? 0}
          sub="YOLOv8 · person / vehicle / crowd"
          colorClass="bg-violet-500/15 text-violet-400"
          glowColor="#8b5cf620"
        />
      </div>

      {/* ── Main content grid ─────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* ANPR Timeline */}
        <div className="card lg:col-span-2">
          <div className="card-header">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <TrendingUp size={14} className="text-orange-400" />
              ANPR Events — last 12 hours
            </div>
            <Link to="/analytics" className="text-xs text-orange-400/80 hover:text-orange-400 flex items-center gap-1">
              Full analytics <ArrowRight size={11} />
            </Link>
          </div>
          <div className="h-52 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={timeline}>
                <defs>
                  <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#f97316" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#f97316" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#112038" />
                <XAxis dataKey="bucket" tick={{ fill: "#475569", fontSize: 10 }}
                  tickFormatter={(v: string) => v.slice(11, 16)} />
                <YAxis tick={{ fill: "#475569", fontSize: 10 }} allowDecimals={false} />
                <Tooltip contentStyle={TT_STYLE}
                  labelFormatter={(v: string) => v.replace("T", " ").slice(0, 16)} />
                <Area type="monotone" dataKey="count" stroke="#f97316" strokeWidth={2}
                  fill="url(#areaGrad)" dot={false} activeDot={{ r: 4, fill: "#f97316" }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Live alerts feed */}
        <div className="card flex flex-col">
          <div className="card-header">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <CircleAlert size={14} className="text-red-400" />
              Live Alert Feed
            </div>
            <Link to="/alerts" className="text-xs text-orange-400/80 hover:text-orange-400 flex items-center gap-1">
              Manage <ArrowRight size={11} />
            </Link>
          </div>
          <div className="flex-1 overflow-y-auto divide-y divide-control-800/50 max-h-52">
            {alerts.length === 0 && (
              <div className="p-4 text-xs text-slate-600 text-center py-8">
                <CheckCircle size={20} className="mx-auto mb-2 text-emerald-600" />
                No open alerts
              </div>
            )}
            {alerts.map((a) => (
              <div key={a.id}
                className={`px-4 py-2.5 flex items-start gap-2.5 ${a.severity === "critical" ? "row-critical" : a.severity === "high" ? "row-high" : ""}`}>
                <span className={`${SEV[a.severity] ?? SEV.low} mt-0.5 shrink-0`}>{a.severity}</span>
                <div className="min-w-0">
                  <div className="text-xs text-slate-200 truncate">{a.message}</div>
                  <div className="text-[10px] text-slate-600 mt-0.5 font-mono">
                    {a.camera_name && <span className="text-slate-500">{a.camera_name} · </span>}
                    {formatDateTime(a.timestamp)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Busiest cameras */}
        <div className="card">
          <div className="card-header">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Database size={14} className="text-cyan-400" />
              Top Camera Volumes
            </div>
            <Link to="/analytics" className="text-xs text-orange-400/80 hover:text-orange-400 flex items-center gap-1">
              ANPR details <ArrowRight size={11} />
            </Link>
          </div>
          <div className="h-52 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={traffic} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#112038" />
                <XAxis type="number" tick={{ fill: "#475569", fontSize: 10 }} allowDecimals={false} />
                <YAxis type="category" dataKey="camera" width={130}
                  tick={{ fill: "#94a3b8", fontSize: 9 }}
                  tickFormatter={(v: string) => v.length > 18 ? v.slice(0, 18) + "…" : v} />
                <Tooltip contentStyle={TT_STYLE} />
                <Bar dataKey="events" fill="#06b6d4" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* System health */}
        <div className="card lg:col-span-2">
          <div className="card-header">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Cpu size={14} className="text-violet-400" />
              System Health
            </div>
            <button onClick={refresh} className="btn-icon" title="Refresh now">
              <RefreshCw size={12} />
            </button>
          </div>
          <div className="p-4 grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              {
                label: "API Backend", value: "Operational",
                ok: true, sub: "Render · guj-ivms-api",
              },
              {
                label: "Sentinel Grid", value: "30 cameras",
                ok: true, sub: `${ov?.cameras_online ?? "—"} online`,
              },
              {
                label: "Alert Simulator",
                value: simStatus?.running ? "Running" : "Stopped",
                ok: simStatus?.running ?? false,
                sub: simStatus ? `${simStatus.events_generated} events · ${simStatus.alerts_generated} alerts` : "…",
              },
              {
                label: "Watchlist Engine", value: "Active",
                ok: (ov?.watchlist_active ?? 0) > 0,
                sub: `${ov?.watchlist_active ?? 0} active entries`,
              },
            ].map((s) => (
              <div key={s.label} className="bg-control-850 rounded-xl p-3 border border-control-800/50">
                <div className="flex items-center gap-1.5 mb-1.5">
                  {s.ok
                    ? <CheckCircle size={12} className="text-emerald-400" />
                    : <AlertTriangle size={12} className="text-amber-400" />}
                  <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">{s.label}</span>
                </div>
                <div className="text-sm font-bold text-white">{s.value}</div>
                <div className="text-[10px] text-slate-600 mt-0.5">{s.sub}</div>
              </div>
            ))}
          </div>

          {/* Simulator control + tier breakdown */}
          <div className="px-4 pb-4 space-y-3">
            <div className="glow-divider" />

            {/* Simulator start/stop */}
            <div className="flex items-center justify-between bg-control-850 rounded-xl px-4 py-3 border border-control-800/50">
              <div>
                <div className="text-xs font-semibold text-slate-300">Analytics Simulator</div>
                <div className="text-[10px] text-slate-600 mt-0.5">
                  {simStatus
                    ? `${simStatus.events_generated.toLocaleString("en-IN")} events generated · ${simStatus.alerts_generated} alerts fired`
                    : "Loading…"}
                </div>
              </div>
              <button
                onClick={toggleSim}
                disabled={simLoading || !simStatus}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  simStatus?.running
                    ? "bg-red-500/15 text-red-400 border border-red-500/25 hover:bg-red-500/25"
                    : "bg-emerald-500/15 text-emerald-400 border border-emerald-500/25 hover:bg-emerald-500/25"
                } disabled:opacity-40`}
              >
                {simStatus?.running
                  ? <><StopCircle size={13} /> Stop Simulator</>
                  : <><PlayCircle size={13} /> Start Simulator</>}
              </button>
            </div>

            {/* Tier breakdown — real DB data */}
            <div className="grid grid-cols-3 gap-2 text-center">
              {tierDisplay.map((t) => (
                <div key={t.label} className="bg-control-850 rounded-xl p-2.5 border border-control-800/50">
                  <div className="text-lg font-bold" style={{ color: t.color }}>{t.label}</div>
                  <div className="text-xs font-semibold text-slate-300">{t.cameras} cams</div>
                  <div className="text-[10px] text-slate-600 mt-0.5">{t.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
