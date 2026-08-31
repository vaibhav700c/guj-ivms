import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ShieldCheck, Loader2 } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../store/auth";

const BASE = import.meta.env.VITE_API_URL ?? "";

export default function Login() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const login = useAuth((s) => s.login);
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const form = new URLSearchParams({ username, password });
      const res = await fetch(`${BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Login failed");
      }
      const data = await res.json();
      login(data.access_token, data.user);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full flex items-center justify-center bg-control-950 relative overflow-hidden">
      <div className="absolute inset-0 opacity-[0.04] bg-[radial-gradient(circle_at_center,_#f97316_0%,_transparent_60%)]" />
      <div className="card w-full max-w-md p-8 relative z-10">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-orange-600/20 border border-orange-600/40 flex items-center justify-center">
            <ShieldCheck className="text-orange-500" size={26} />
          </div>
          <div>
            <h1 className="text-lg font-bold">Gujarat IVMS</h1>
            <p className="text-xs text-slate-500">
              Integrated Video Management &amp; Analytics — Control Room
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-xs text-slate-400 mb-1 block">Username</label>
            <input
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">Password</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
          <button className="btn-primary w-full justify-center py-2.5" disabled={loading}>
            {loading && <Loader2 size={16} className="animate-spin" />}
            Sign in to Control Room
          </button>
        </form>

        <p className="mt-6 text-[11px] text-slate-500 text-center">
          Demo credentials: <span className="font-mono text-slate-400">admin / admin123</span>
          <br />
          JWT + RBAC secured · PBKDF2 password hashing
        </p>
      </div>
    </div>
  );
}
