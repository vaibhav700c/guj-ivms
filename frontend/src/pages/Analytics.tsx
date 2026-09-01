import { useEffect, useState } from "react";
import { Download, TrendingUp, Camera, Car, Users, Activity } from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { api, formatDateTime } from "../lib/api";

const BASE = import.meta.env.VITE_API_URL ?? "";

const PIE_COLORS = ["#f97316", "#06b6d4", "#8b5cf6", "#10b981", "#f43f5e", "#f59e0b", "#64748b"];
const TT = { background: "#0d1a2e", border: "1px solid #1e3352", borderRadius: 10, fontSize: 11, color: "#94a3b8" };

interface FaceEvent {
  id: number; camera_name: string | null; detected_identifier: string | null;
  confidence: number | null; timestamp: string; event_type: string;
}

function SectionTitle({ icon: Icon, children }: { icon: React.ElementType; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
      <Icon size={14} className="text-orange-400" />
      {children}
    </div>
  );
}

export default function Analytics() {
  const [byHour, setByHour] = useState<{ hour: string; count: number }[]>([]);
  const [byCamera, setByCamera] = useState<{ camera: string; city: string; events: number }[]>([]);
  const [byType, setByType] = useState<{ event_type: string; count: number }[]>([]);
  const [tiers, setTiers] = useState<{ tier: string; count: number; description: string }[]>([]);
  const [overview, setOverview] = useState<Record<string, number>>({});
  const [timeline, setTimeline] = useState<{ bucket: string; count: number }[]>([]);
  const [faceEvents, setFaceEvents] = useState<FaceEvent[]>([]);

  useEffect(() => {
    api<{ hour: string; count: number }[]>("/vehicles/traffic/by-hour").then(setByHour).catch(() => undefined);
    api<{ camera: string; city: string; events: number }[]>("/vehicles/traffic/by-camera?limit=10").then(setByCamera).catch(() => undefined);
    api<{ event_type: string; count: number }[]>("/analytics/detections/by-type").then(setByType).catch(() => undefined);
    api<{ tier: string; count: number; description: string }[]>("/analytics/tiers/coverage").then(setTiers).catch(() => undefined);
    api<Record<string, number>>("/analytics/overview").then(setOverview).catch(() => undefined);
    api<{ bucket: string; count: number }[]>("/analytics/events/timeline?hours=24").then(setTimeline).catch(() => undefined);
    // Face detection events (detection events with face type)
    api<{ items: FaceEvent[] }>("/alerts?limit=20&alert_type=wanted_person").then((r) => setFaceEvents(r.items ?? [])).catch(() => undefined);
  }, []);

  return (
    <div className="space-y-6 max-w-[1500px] animate-fade-in">

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Analytics & Reports</h1>
          <p className="page-subtitle">
            Metadata analytics only — raw video never leaves departmental systems (plan §4)
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {[
            { href: `${BASE}/api/v1/reports/alerts.csv`, label: "Alerts CSV" },
            { href: `${BASE}/api/v1/reports/anpr.csv`, label: "ANPR CSV" },
            { href: `${BASE}/api/v1/reports/cameras.csv`, label: "Registry CSV" },
            { href: `${BASE}/api/v1/reports/alerts.pdf`, label: "Alerts PDF" },
            { href: `${BASE}/api/v1/reports/anpr.pdf`, label: "ANPR PDF" },
            { href: `${BASE}/api/v1/reports/cameras.pdf`, label: "Registry PDF" },
          ].map((d) => (
            <a key={d.href} className="btn-ghost text-xs" href={d.href} download>
              <Download size={12} /> {d.label}
            </a>
          ))}
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Total ANPR Events", value: (overview.anpr_events_total ?? 0).toLocaleString("en-IN"), icon: Car, color: "text-orange-400" },
          { label: "Events (24h)", value: (overview.anpr_events_24h ?? 0).toLocaleString("en-IN"), icon: TrendingUp, color: "text-cyan-400" },
          { label: "Detections (24h)", value: (overview.detections_24h ?? 0).toLocaleString("en-IN"), icon: Activity, color: "text-violet-400" },
          { label: "Registry Vehicles", value: (overview.registry_vehicles ?? 0).toLocaleString("en-IN"), icon: Users, color: "text-emerald-400" },
        ].map((k) => (
          <div key={k.label} className="card p-4">
            <k.icon size={16} className={`mb-2 ${k.color}`} />
            <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
            <div className="text-xs text-slate-500 mt-1">{k.label}</div>
          </div>
        ))}
      </div>

      {/* Charts row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* 24h timeline */}
        <div className="card">
          <div className="card-header">
            <SectionTitle icon={TrendingUp}>ANPR Events — last 24 hours</SectionTitle>
          </div>
          <div className="h-56 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={timeline}>
                <defs>
                  <linearGradient id="grad24h" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#f97316" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#f97316" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#112038" />
                <XAxis dataKey="bucket" tick={{ fill: "#475569", fontSize: 10 }}
                  tickFormatter={(v: string) => v.slice(11, 16)} />
                <YAxis tick={{ fill: "#475569", fontSize: 10 }} allowDecimals={false} />
                <Tooltip contentStyle={TT} labelFormatter={(v: string) => v.replace("T", " ").slice(0, 16)} />
                <Area type="monotone" dataKey="count" stroke="#f97316" fill="url(#grad24h)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Hourly pattern */}
        <div className="card">
          <div className="card-header">
            <SectionTitle icon={TrendingUp}>Traffic Volume by Hour of Day</SectionTitle>
          </div>
          <div className="h-56 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={byHour}>
                <defs>
                  <linearGradient id="gradH" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#06b6d4" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#06b6d4" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#112038" />
                <XAxis dataKey="hour" tick={{ fill: "#475569", fontSize: 10 }} interval={2} />
                <YAxis tick={{ fill: "#475569", fontSize: 10 }} allowDecimals={false} />
                <Tooltip contentStyle={TT} />
                <Area type="monotone" dataKey="count" stroke="#06b6d4" fill="url(#gradH)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Top cameras */}
        <div className="card">
          <div className="card-header">
            <SectionTitle icon={Camera}>Top Cameras by ANPR Volume</SectionTitle>
          </div>
          <div className="h-56 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={byCamera} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#112038" />
                <XAxis type="number" tick={{ fill: "#475569", fontSize: 10 }} allowDecimals={false} />
                <YAxis type="category" dataKey="camera" width={160}
                  tick={{ fill: "#94a3b8", fontSize: 9 }}
                  tickFormatter={(v: string) => v.length > 22 ? v.slice(0, 22) + "…" : v} />
                <Tooltip contentStyle={TT} />
                <Bar dataKey="events" fill="#f97316" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Detection class pie */}
        <div className="card">
          <div className="card-header">
            <SectionTitle icon={Activity}>Detection Events by Class</SectionTitle>
          </div>
          <div className="h-56 p-4">
            {byType.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={byType} dataKey="count" nameKey="event_type" innerRadius={50} outerRadius={80} paddingAngle={4}>
                    {byType.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Legend wrapperStyle={{ fontSize: 11, color: "#64748b" }} />
                  <Tooltip contentStyle={TT} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex flex-col items-center justify-center gap-2 text-slate-600">
                <Activity size={24} />
                <span className="text-xs">No detection data yet — simulator running…</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Analytics tier coverage */}
      <div className="card">
        <div className="card-header">
          <SectionTitle icon={Camera}>Analytics Tiering Coverage (plan §4)</SectionTitle>
        </div>
        <div className="p-5 grid md:grid-cols-3 gap-4">
          {tiers.map((t) => {
            const max = Math.max(...tiers.map((x) => x.count), 1);
            const colors = { A: "#f97316", B: "#06b6d4", C: "#475569" };
            const color = colors[t.tier as keyof typeof colors] ?? "#475569";
            return (
              <div key={t.tier} className="bg-control-850 rounded-xl p-4 border border-control-800/50">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-2xl font-black" style={{ color }}>Tier {t.tier}</span>
                  <span className="font-mono text-xl font-bold text-white">{t.count}</span>
                </div>
                <div className="h-1.5 bg-control-800 rounded-full overflow-hidden mb-2">
                  <div className="h-full rounded-full transition-all duration-1000"
                    style={{ width: `${(t.count / max) * 100}%`, background: color }} />
                </div>
                <div className="text-xs text-slate-500">{t.description}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Face / Person match events */}
      <div className="card">
        <div className="card-header">
          <SectionTitle icon={Users}>Face & Person Match Events</SectionTitle>
          <span className="text-xs text-slate-500">{faceEvents.length} recent matches</span>
        </div>
        {faceEvents.length > 0 ? (
          <table className="w-full">
            <thead>
              <tr className="border-b border-control-800">
                <th className="table-head">Camera</th>
                <th className="table-head">Subject</th>
                <th className="table-head">Confidence</th>
                <th className="table-head">Timestamp</th>
                <th className="table-head">Type</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-control-800/50">
              {faceEvents.map((ev) => (
                <tr key={ev.id} className="table-row">
                  <td className="table-cell font-medium">{ev.camera_name ?? "—"}</td>
                  <td className="table-cell font-mono text-orange-300">{ev.detected_identifier ?? "—"}</td>
                  <td className="table-cell">
                    {ev.confidence != null ? (
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-16 bg-control-800 rounded-full overflow-hidden">
                          <div className="h-full bg-violet-500 rounded-full" style={{ width: `${ev.confidence * 100}%` }} />
                        </div>
                        <span className="font-mono text-xs">{(ev.confidence * 100).toFixed(0)}%</span>
                      </div>
                    ) : "—"}
                  </td>
                  <td className="table-cell font-mono text-xs">{formatDateTime(ev.timestamp)}</td>
                  <td className="table-cell">
                    <span className="badge bg-violet-500/15 text-violet-400 border border-violet-500/25">{ev.event_type ?? "face"}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="p-10 text-center text-slate-600 text-sm">
            No face match events yet — simulator will generate them when watchlist persons are active
          </div>
        )}
      </div>
    </div>
  );
}
