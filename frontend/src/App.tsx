import { useEffect, useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Cameras from "./pages/Cameras";
import LiveView from "./pages/LiveView";
import MapView from "./pages/MapView";
import Vehicles from "./pages/Vehicles";
import Alerts from "./pages/Alerts";
import Watchlist from "./pages/Watchlist";
import Analytics from "./pages/Analytics";
import AnprDetections from "./pages/AnprDetections";
import { useAuth } from "./store/auth";
import { api } from "./lib/api";

export default function App() {
  const { token, user, login } = useAuth();
  const [checking, setChecking] = useState(!token && !user);

  // Detect backend demo mode (REQUIRE_AUTH=false): /auth/me returns a demo user.
  useEffect(() => {
    if (token || user) return;
    setChecking(true);
    api<{ username: string; role: string; auth_mode: string }>("/auth/me")
      .then((me) => {
        if (me.auth_mode === "disabled") {
          login("", { id: 0, username: "demo", full_name: "Demo Session", role: me.role, department: null });
        }
      })
      .catch(() => undefined)
      .finally(() => setChecking(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (checking) {
    return (
      <div className="h-full flex items-center justify-center bg-control-950">
        <Loader2 className="animate-spin text-orange-500" size={32} />
      </div>
    );
  }

  const allow = !!token || !!user;

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={allow ? <Layout /> : <Navigate to="/login" replace />} path="/">
        <Route index element={<Dashboard />} />
        <Route path="cameras" element={<Cameras />} />
        <Route path="live" element={<LiveView />} />
        <Route path="map" element={<MapView />} />
        <Route path="vehicles" element={<Vehicles />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="watchlist" element={<Watchlist />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="anpr" element={<AnprDetections />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
