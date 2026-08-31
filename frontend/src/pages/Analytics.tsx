import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { api } from "../lib/api";

const BASE = import.meta.env.VITE_API_URL ?? "";

const PIE_COLORS = ["#f97316", "#0ea5e9", "#8b5cf6", "#10b981", "#f43f5e", "#f59e0b"];

export default function Analytics() {
  const [byHour, setByHour] = useState<{ hour: string; count: number }[]>([]);
  const [byCamera, setByCamera] = useState<{ camera: string; city: string; events: number }[]>([]);
  const [byType, setByType] = useState<{ event_type: string; count: number }[]>([]);
  const [tiers, setTiers] = useState<{ tier: string; count: number; description: string }[]>([]);
  const [overview, setOverview] = useState<Record<string, number>>({});

  useEffect(() => {
    api<{ hour: string; count: number }[]>("/vehicles/traffic/by-hour").then(setByHour).catch(() => undefined);
    api<{ camera: string; city: string; events: number }[]>("/vehicles/traffic/by-camera?limit=10").then(setByCamera).catch(() => undefined);
    api<{ event_type: string; count: number }[]>("/analytics/detections/by-type").then(setByType).catch(() => undefined);
    api<{ tier: string; count: number; description: string }[]>("/analytics/tiers/coverage").then(setTiers).catch(() => undefined);
    api<Record<string, number>>("/analytics/overview").then(setOverview).catch(() => undefined);
  }, []);

  const tooltipStyle = { background: "#1e293b", border: "1px solid #334155", borderRadius: 8, fontSize: 12 };

  return (
    <div className="space-y-5 max-w-[1400px]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Analytics &amp; Reports</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Metadata analytics only — raw video never leaves departmental systems
          </p>
        </div>
        <div className="flex gap-2">
          <a className="btn-ghost" href={`${BASE}/api/v1/reports/alerts.csv`}><Download size={13} /> Alerts CSV</a>
          <a className="btn-ghost" href={`${BASE}/api/v1/reports/anpr.csv`}><Download size={13} /> ANPR CSV</a>
          <a className="btn-ghost" href={`${BASE}/api/v1/reports/cameras.csv`}><Download size={13} /> Registry CSV</a>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="card">
          <div className="card-header text-sm font-semibold">ANPR Traffic by Hour of Day</div>
          <div className="h-64 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={byHour}>
                <defs>
                  <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#f97316" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#f97316" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="hour" tick={{ fill: "#64748b", fontSize: 10 }} interval={2} />
                <YAxis tick={{ fill: "#64748b", fontSize: 10 }} allowDecimals={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Area type="monotone" dataKey="count" stroke="#f97316" fill="url(#grad)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <div className="card-header text-sm font-semibold">Top 10 Cameras by ANPR Volume</div>
          <div className="h-64 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={byCamera} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} allowDecimals={false} />
                <YAxis type="category" dataKey="camera" width={180}
                  tick={{ fill: "#94a3b8", fontSize: 9 }}
                  tickFormatter={(v: string) => v.length > 26 ? v.slice(0, 26) + "…" : v} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="events" fill="#0ea5e9" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <div className="card-header text-sm font-semibold">Detection Events by Class</div>
          <div className="h-64 p-4">
            {byType.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={byType} dataKey="count" nameKey="event_type" innerRadius={55} outerRadius={85} paddingAngle={3}>
                    {byType.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Tooltip contentStyle={tooltipStyle} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-slate-500">No detection data yet…</div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header text-sm font-semibold">Analytics Tiering Strategy (§4)</div>
          <div className="p-4 space-y-3">
            {tiers.map((t) => {
              const max = Math.max(...tiers.map((x) => x.count), 1);
              return (
                <div key={t.tier}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="font-semibold text-slate-200">Tier {t.tier}</span>
                    <span className="font-mono text-slate-400">{t.count} cameras</span>
                  </div>
                  <div className="h-2 rounded bg-control-800 overflow-hidden">
                    <div className="h-full rounded" style={{
                      width: `${(t.count / max) * 100}%`,
                      background: t.tier === "A" ? "#f97316" : t.tier === "B" ? "#0ea5e9" : "#64748b",
                    }} />
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5">{t.description}</div>
                </div>
              );
            })}
            <div className="grid grid-cols-2 gap-2 pt-2 border-t border-control-800 text-xs">
              <div className="bg-control-850 rounded-lg p-2">
                <div className="font-mono text-orange-400 text-base">{overview.anpr_events_total ?? "—"}</div>
                <div className="text-slate-500">Total ANPR events</div>
              </div>
              <div className="bg-control-850 rounded-lg p-2">
                <div className="font-mono text-sky-400 text-base">{overview.detections_24h ?? "—"}</div>
                <div className="text-slate-500">Detections (24h)</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
