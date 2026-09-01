import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Video, MonitorPlay, Map as MapIcon,
  Car, Siren, ListChecks, BarChart3, ShieldCheck, LogOut,
  Bell, BellOff, Wifi, WifiOff, ChevronRight, ScanLine,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../store/auth";
import { wsUrl } from "../lib/api";

const NAV = [
  { to: "/",          label: "Dashboard",      icon: LayoutDashboard },
  { to: "/cameras",   label: "Camera Registry", icon: Video },
  { to: "/live",      label: "Live View",       icon: MonitorPlay },
  { to: "/map",       label: "GIS Map",         icon: MapIcon },
  { to: "/vehicles",  label: "Vehicle Search",  icon: Car },
  { to: "/alerts",    label: "Live Alerts",     icon: Siren },
  { to: "/anpr",      label: "ANPR Detections", icon: ScanLine },
  { to: "/watchlist", label: "Watchlist",        icon: ListChecks },
  { to: "/analytics", label: "Analytics",        icon: BarChart3 },
];

interface Alert { severity: string; message: string; timestamp: string; }

const ALERT_AUDIO_KEY = "ivms_sound_enabled";

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [connected, setConnected] = useState(false);
  const [unread, setUnread] = useState(0);
  const [ticker, setTicker] = useState<Alert[]>([]);
  const [soundOn, setSoundOn] = useState(() => localStorage.getItem(ALERT_AUDIO_KEY) !== "false");
  const [expanded, setExpanded] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const sidebarRef = useRef<HTMLDivElement>(null);

  // Subtle beep for critical alerts
  const playBeep = useCallback(() => {
    if (!soundOn) return;
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.type = "sine"; osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.15, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
      osc.start(); osc.stop(ctx.currentTime + 0.4);
    } catch { /* no audio context */ }
  }, [soundOn]);

  const toggleSound = () => {
    setSoundOn((v) => { localStorage.setItem(ALERT_AUDIO_KEY, String(!v)); return !v; });
  };

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === "alert") {
            setUnread((u) => u + 1);
            const a: Alert = { severity: data.severity ?? "medium", message: data.message ?? "Alert", timestamp: data.timestamp ?? new Date().toISOString() };
            setTicker((t) => [a, ...t].slice(0, 20));
            if (data.severity === "critical" || data.severity === "high") playBeep();
          }
        } catch { /* ignore */ }
      };
      ws.onclose = () => { setConnected(false); retry = setTimeout(connect, 3000); };
    };
    connect();
    return () => { clearTimeout(retry); ws?.close(); };
  }, [playBeep]);

  // Close sidebar on outside click (mobile)
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (expanded && sidebarRef.current && !sidebarRef.current.contains(e.target as Node)) {
        setExpanded(false);
      }
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [expanded]);

  const tickerText = ticker.slice(0, 5).map((a) => `● ${a.severity.toUpperCase()}: ${a.message}`).join("   ·   ");

  return (
    <div className="h-full flex flex-col bg-control-950">

      {/* ── Top bar ─────────────────────────────────────── */}
      <header className="h-12 shrink-0 flex items-center px-4 gap-4 border-b border-control-800/60 relative z-30"
        style={{ background: "linear-gradient(90deg, #091120 0%, #0d1a2e 50%, #091120 100%)" }}>

        {/* Logo */}
        <div className="flex items-center gap-2.5 shrink-0">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: "linear-gradient(135deg, #f97316, #c2410c)", boxShadow: "0 0 16px #f9731640" }}>
            <ShieldCheck size={16} className="text-white" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-bold tracking-wide text-white">Gujarat IVMS</div>
            <div className="text-[9px] text-slate-500 uppercase tracking-widest">Integrated Video Management</div>
          </div>
        </div>

        {/* Alert ticker */}
        <div className="flex-1 min-w-0 mx-4 overflow-hidden">
          {tickerText ? (
            <div className="ticker-wrap text-[11px] font-mono">
              <div className="ticker-inner text-amber-400/70">
                {tickerText}
                <span className="mx-16" />
                {tickerText}
              </div>
            </div>
          ) : (
            <div className="text-[11px] text-slate-600 font-mono">
              No active alerts · Sentinel Grid monitoring 30 cameras
            </div>
          )}
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-3 shrink-0">
          {/* WS status */}
          <div className="flex items-center gap-1.5 text-[11px]">
            {connected
              ? <><div className="live-dot" /><span className="text-emerald-400">Live</span></>
              : <><WifiOff size={11} className="text-red-400" /><span className="text-red-400">Reconnecting</span></>}
          </div>

          {/* Sound toggle */}
          <button onClick={toggleSound} className="btn-icon" title={soundOn ? "Mute alerts" : "Enable alert sound"}>
            {soundOn ? <Bell size={13} /> : <BellOff size={13} className="text-slate-600" />}
          </button>

          {/* Clock */}
          <LiveClock />

          {/* User */}
          <div className="text-right hidden sm:block">
            <div className="text-xs font-semibold text-slate-300">{user?.full_name || user?.username || "—"}</div>
            <div className="text-[9px] uppercase tracking-widest text-slate-600">{user?.role}</div>
          </div>

          {user && user.username !== "demo" && (
            <button onClick={() => { logout(); navigate("/login"); }} className="btn-icon" title="Sign out">
              <LogOut size={13} />
            </button>
          )}
        </div>
      </header>

      <div className="flex flex-1 min-h-0">

        {/* ── Sidebar ─────────────────────────────────────── */}
        <nav
          ref={sidebarRef}
          onMouseEnter={() => setExpanded(true)}
          onMouseLeave={() => setExpanded(false)}
          className="shrink-0 border-r border-control-800/60 flex flex-col py-3 gap-0.5 overflow-hidden z-20 transition-all duration-300"
          style={{
            width: expanded ? "13rem" : "3.25rem",
            background: "linear-gradient(180deg, #091120 0%, #050d1a 100%)",
          }}
        >
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={() => setUnread(0)}
              className={({ isActive }) =>
                `relative flex items-center gap-3 mx-1.5 px-2.5 py-2.5 rounded-xl text-sm transition-all duration-200 group overflow-hidden ${
                  isActive
                    ? "bg-orange-500/12 text-orange-400 border border-orange-500/20"
                    : "text-slate-500 hover:text-slate-200 hover:bg-control-800/50 border border-transparent"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-orange-400 rounded-r" />
                  )}
                  <Icon size={16} className="shrink-0" />
                  <span
                    className="truncate font-medium whitespace-nowrap transition-all duration-300"
                    style={{ opacity: expanded ? 1 : 0, width: expanded ? "auto" : 0 }}
                  >
                    {label}
                  </span>
                  {to === "/alerts" && unread > 0 && (
                    <span className="ml-auto badge-critical text-[10px] px-1.5 py-0 shrink-0"
                      style={{ display: expanded ? "inline-flex" : "none" }}>
                      {unread}
                    </span>
                  )}
                  {!expanded && to === "/alerts" && unread > 0 && (
                    <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-red-500" />
                  )}
                </>
              )}
            </NavLink>
          ))}

          {/* Bottom expand hint */}
          <div className="mt-auto mx-1.5 px-2.5 py-2 flex items-center gap-2 text-[10px] text-slate-700">
            <ChevronRight size={10} className={`transition-transform duration-300 ${expanded ? "rotate-180" : ""}`} />
            {expanded && <span>Hover to expand</span>}
          </div>
        </nav>

        {/* ── Page content ─────────────────────────────────────── */}
        <main className="flex-1 overflow-y-auto p-5 min-w-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function LiveClock() {
  const [t, setT] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setT(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="font-mono text-[11px] text-slate-500 tabular-nums hidden md:block">
      {t.toLocaleTimeString("en-IN", { hour12: false })}
    </div>
  );
}
