import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Video,
  Activity,
  Siren,
  Database,
  TrendingUp,
  Car,
  CircleAlert,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { api, formatDateTime } from "../lib/api";

interface Overview {
  cameras_total: number;
  cameras_online: number;
  cameras_offline: number;
  anpr_events_24h: number;
  anpr_events_total: number;
  detections_24h: number;
  watchlist_active: number;
  registry_vehicles: number;
}

interface AlertItem {
  id: number;
  severity: string;
  message: string;
  status: string;
  timestamp: string;
  camera_name: string | null;
}

const SEV_COLORS: Record<string, string> = {
  critical: "bg-red-500/15 text-red-400 border border-red-500/30",
  high: "bg-orange-500/15 text-orange-400 border border-orange-500/30",
  medium: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  low: "bg-slate-500/15 text-slate-400 border border-slate-500/30",
};

function StatCard({ icon: Icon, label, value, sub, color }: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
  color: string;
}) {
  return (
    <div className="card p-4 flex items-start gap-3">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color}`}>
        <Icon size={20} />
      </div>
      <div>
        <div className="text-2xl font-bold leading-none">{value}</div>
        <div className="text-xs text-slate-400 mt-1">{label}</div>
        {sub && <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [timeline, setTimeline] = useState<{ bucket: string; count: number }[]>([]);
  const [traffic, setTraffic] = useState<{ camera: string; city: string; events: number }[]>([]);

  useEffect(() => {
    api<Overview>("/analytics/overview").then(setOv).catch(() => undefined);
    api<{ items: AlertItem[] }>("/alerts?limit=8").then((r) => setAlerts(r.items)).catch(() => undefined);
    api<{ bucket: string; count: number }[]>("/analytics/events/timeline?hours=12")
      .then(setTimeline).catch(() => undefined);
    api<{ camera: string; city: string; events: number }[]>("/vehicles/traffic/by-camera?limit=6")
      .then(setTraffic).catch(() => undefined);
  }, []);

  const onlinePct = ov ? Math.round((ov.cameras_online / Math.max(ov.cameras_total, 1)) * 100) : 0;

  return (
    <div className="space-y-5 max-w-[1400px]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Control Room Dashboard</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Analytics at the edge · correlation at the center — state-wide overview
          </p>
        </div>
        <div className="text-xs text-slate-500 font-mono">
          {new Date().toLocaleString("en-IN", { hour12: false })}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard icon={Video} label="Cameras Online"
          value={ov ? `${ov.cameras_online}/${ov.cameras_total}` : "—"}
          sub={ov ? `${onlinePct}% fleet availability` : ""}
          color="bg-emerald-500/15 text-emerald-400" />
        <StatCard icon={Car} label="ANPR Events (24h)"
          value={ov ? ov.anpr_events_24h.toLocaleString("en-IN") : "—"}
          sub={ov ? `${ov.anpr_events_total.toLocaleString("en-IN")} lifetime` : ""}
          color="bg-sky-500/15 text-sky-400" />
        <StatCard icon={Siren} label="Active Watchlist"
          value={ov ? ov.watchlist_active : "—"}
          sub={ov ? `${ov.registry_vehicles} VAHAN-like records` : ""}
          color="bg-red-500/15 text-red-400" />
        <StatCard icon={Activity} label="Detections (24h)"
          value={ov ? ov.detections_24h.toLocaleString("en-IN") : "—"}
          sub="YOLO person/vehicle/crowd"
          color="bg-violet-500/15 text-violet-400" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="card lg:col-span-2">
          <div className="card-header">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <TrendingUp size={15} className="text-orange-500" />
              ANPR Events — last 12 hours
            </div>
            <Link to="/analytics" className="text-xs text-orange-400 hover:underline">Full analytics →</Link>
          </div>
          <div className="h-56 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={timeline}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="bucket" tick={{ fill: "#64748b", fontSize: 10 }}
                  tickFormatter={(v: string) => v.slice(11, 16)} />
                <YAxis tick={{ fill: "#64748b", fontSize: 10 }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(v: string) => v.replace("T", " ").slice(0, 16)} />
                <Bar dataKey="count" fill="#f97316" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <CircleAlert size={15} className="text-red-400" />
              Latest Watchlist Alerts
            </div>
            <Link to="/alerts" className="text-xs text-orange-400 hover:underline">All alerts →</Link>
          </div>
          <div className="divide-y divide-control-800 max-h-56 overflow-y-auto">
            {alerts.length === 0 && (
              <div className="p-4 text-xs text-slate-500">No alerts yet — simulator is generating…</div>
            )}
            {alerts.map((a) => (
              <div key={a.id} className="px-4 py-2.5 flex items-start gap-2">
                <span className={`badge mt-0.5 ${SEV_COLORS[a.severity] ?? SEV_COLORS.low}`}>{a.severity}</span>
                <div className="min-w-0">
                  <div className="text-xs text-slate-200 truncate">{a.message}</div>
                  <div className="text-[10px] text-slate-500 mt-0.5 font-mono">{formatDateTime(a.timestamp)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card lg:col-span-3">
          <div className="card-header">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Database size={15} className="text-sky-400" />
              Busiest Camera Locations (ANPR volume)
            </div>
          </div>
          <div className="p-2">
            <table className="w-full">
              <thead>
                <tr className="border-b border-control-800">
                  <th className="table-head">Camera</th>
                  <th className="table-head">City</th>
                  <th className="table-head text-right">Events</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-control-800/60">
                {traffic.map((t) => (
                  <tr key={t.camera} className="hover:bg-control-800/40">
                    <td className="table-cell font-medium">{t.camera}</td>
                    <td className="table-cell">{t.city}</td>
                    <td className="table-cell text-right font-mono text-orange-400">{t.events}</td>
                  </tr>
                ))}
                {traffic.length === 0 && (
                  <tr><td className="table-cell text-slate-500" colSpan={3}>Waiting for ANPR data…</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
