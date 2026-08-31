import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Video,
  MonitorPlay,
  Map as MapIcon,
  Car,
  Siren,
  ListChecks,
  BarChart3,
  ShieldCheck,
  LogOut,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useAuth } from "../store/auth";
import { wsUrl } from "../lib/api";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/cameras", label: "Camera Registry", icon: Video },
  { to: "/live", label: "Live View", icon: MonitorPlay },
  { to: "/map", label: "GIS Map", icon: MapIcon },
  { to: "/vehicles", label: "Vehicle Search", icon: Car },
  { to: "/alerts", label: "Live Alerts", icon: Siren },
  { to: "/watchlist", label: "Watchlist", icon: ListChecks },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [connected, setConnected] = useState(false);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === "alert") setUnread((u) => u + 1);
        } catch {
          /* ignore */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        retry = setTimeout(connect, 3000);
      };
    };
    connect();
    return () => {
      clearTimeout(retry);
      ws?.close();
    };
  }, []);

  return (
    <div className="h-full flex flex-col">
      {/* Top bar */}
      <header className="h-14 flex items-center justify-between px-4 border-b border-control-800 bg-control-900">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-orange-600/20 border border-orange-600/40 flex items-center justify-center">
            <ShieldCheck className="text-orange-500" size={20} />
          </div>
          <div>
            <div className="font-semibold text-sm leading-tight">
              Gujarat IVMS
              <span className="ml-2 text-[10px] font-mono px-1.5 py-0.5 rounded bg-control-800 text-slate-400 align-middle">
                v1.0
              </span>
            </div>
            <div className="text-[11px] text-slate-500">
              Integrated Video Management &amp; Analytics Platform
            </div>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5 text-xs">
            <span
              className={`w-2 h-2 rounded-full ${connected ? "bg-emerald-500 animate-pulse" : "bg-red-500"}`}
            />
            <span className="text-slate-400">
              {connected ? "Live feed connected" : "Reconnecting…"}
            </span>
          </div>
          <div className="text-right">
            <div className="text-xs font-medium text-slate-300">
              {user?.full_name || user?.username || "—"}
            </div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">
              {user?.role ?? ""}
            </div>
          </div>
          {user && user.username !== "demo" && (
            <button
              onClick={() => {
                logout();
                navigate("/login");
              }}
              className="btn-ghost"
              title="Sign out"
            >
              <LogOut size={14} />
            </button>
          )}
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <nav className="w-56 shrink-0 border-r border-control-800 bg-control-900 p-3 space-y-1 overflow-y-auto">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={() => setUnread(0)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? "bg-orange-600/15 text-orange-400 border border-orange-600/30"
                    : "text-slate-400 hover:bg-control-800 hover:text-slate-200 border border-transparent"
                }`
              }
            >
              <Icon size={16} />
              <span className="flex-1">{label}</span>
              {to === "/alerts" && unread > 0 && (
                <span className="badge bg-red-500/20 text-red-400">{unread}</span>
              )}
            </NavLink>
          ))}
          <div className="pt-4 mt-4 border-t border-control-800 text-[10px] text-slate-600 leading-relaxed px-1">
            Hybrid architecture — Model 1+2+3.
            <br />
            Open-source · zero vendor lock-in.
          </div>
        </nav>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
