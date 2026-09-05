import { useEffect, useState } from "react";
import {
  MonitorPlay, Grid2X2, Grid3X3, LayoutGrid, Search, X,
} from "lucide-react";
import { api } from "../lib/api";
import StreamTile, { proxyHlsUrl, type StreamCamera } from "../components/StreamTile";

const SENTINEL_PORTAL = "https://live.sentinelgujarat.in";

type Camera = StreamCamera;

const LAYOUTS = { "2×2": 4, "3×3": 9, "4×4": 16 } as const;
type LayoutKey = keyof typeof LAYOUTS;

export default function LiveView() {
  const [allCams, setAllCams] = useState<Camera[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // 2x2 by default: the CDN sits behind Cloudflare, which rate-limits by source
  // IP, and the backend proxies every viewer through one address. Fewer tiles
  // opening at once keeps the grid reliable; operators can still switch up.
  const [layout, setLayout] = useState<LayoutKey>("2×2");
  const [clock, setClock] = useState(new Date());
  const [focus, setFocus] = useState<Camera | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    api<{ items: Camera[] }>("/cameras?limit=100")
      .then((r) => {
        const cams = r.items.filter((c) => c.stream_url);
        setAllCams(cams);
        setSelected(new Set(cams.slice(0, 4).map((c) => c.id)));
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const grid = LAYOUTS[layout];
  const shown = allCams.filter((c) => selected.has(c.id)).slice(0, grid);

  const filtered = allCams.filter((c) =>
    !search || c.name.toLowerCase().includes(search.toLowerCase()) || (c.city ?? "").toLowerCase().includes(search.toLowerCase())
  );

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < grid) next.add(id);
      return next;
    });
  };

  const GRID_CLASS: Record<LayoutKey, string> = {
    "2×2": "grid-cols-1 md:grid-cols-2",
    "3×3": "grid-cols-2 md:grid-cols-3",
    "4×4": "grid-cols-2 md:grid-cols-4",
  };

  return (
    <div className="flex gap-4 max-w-[1600px] animate-fade-in" style={{ height: "calc(100vh - 5.5rem)" }}>

      {/* ── Camera Selector Sidebar ── */}
      <div className="w-56 shrink-0 card flex flex-col overflow-hidden">
        <div className="p-3 border-b border-control-800">
          <div className="text-xs font-semibold text-slate-400 mb-2 flex items-center justify-between">
            <span>Camera Selector</span>
            <span className="text-[10px] text-slate-600">{selected.size}/{grid}</span>
          </div>
          <div className="relative">
            <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-600" />
            <input className="input pl-7 text-xs py-1.5" placeholder="Search…"
              value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {filtered.map((c) => {
            const on = selected.has(c.id);
            const atMax = selected.size >= grid && !on;
            return (
              <button
                key={c.id}
                disabled={atMax}
                onClick={() => toggle(c.id)}
                className={`w-full text-left px-2.5 py-2 rounded-lg text-xs transition-all flex items-start gap-2 ${
                  on ? "bg-orange-500/15 text-orange-300 border border-orange-500/20"
                    : atMax ? "opacity-30 cursor-not-allowed text-slate-600"
                    : "text-slate-400 hover:bg-control-800 hover:text-slate-200"
                }`}>
                <div className={`w-1.5 h-1.5 rounded-full mt-0.5 shrink-0 ${c.status === "online" ? "bg-emerald-400" : "bg-red-400"}`} />
                <div className="min-w-0">
                  <div className="truncate font-medium">{c.name}</div>
                  <div className="text-[9px] text-slate-600 font-mono truncate">{c.external_id} · {c.city}</div>
                </div>
              </button>
            );
          })}
        </div>

        <div className="p-2 border-t border-control-800">
          <button className="btn-ghost w-full text-xs justify-center py-1.5"
            onClick={() => setSelected(new Set(allCams.slice(0, grid).map((c) => c.id)))}>
            Reset to default
          </button>
        </div>
      </div>

      {/* ── Main video area ── */}
      <div className="flex-1 flex flex-col gap-3 min-w-0">

        {/* Toolbar */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="page-title text-lg">Unified Live View</h1>
            <p className="text-[11px] text-slate-600">
              {shown.length} streams · HLS proxied · AES-128 decrypted ·{" "}
              <a href={SENTINEL_PORTAL} target="_blank" rel="noopener noreferrer" className="text-orange-400 hover:underline">
                live.sentinelgujarat.in ↗
              </a>
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            {(Object.keys(LAYOUTS) as LayoutKey[]).map((k) => (
              <button key={k} onClick={() => { setLayout(k); setSelected(new Set(allCams.slice(0, LAYOUTS[k]).map((c) => c.id))); }}
                className={`btn text-xs py-1.5 px-2.5 ${layout === k ? "bg-orange-500/15 text-orange-400 border border-orange-500/25" : "btn-ghost"}`}>
                {k === "2×2" ? <Grid2X2 size={13} /> : k === "3×3" ? <Grid3X3 size={13} /> : <LayoutGrid size={13} />}
                {k}
              </button>
            ))}
          </div>
        </div>

        {/* Fullscreen focus view */}
        {focus ? (
          <div className="flex-1 relative card overflow-hidden">
            <button className="absolute top-3 right-3 z-20 btn-ghost text-xs gap-1.5 py-1 px-2"
              onClick={() => setFocus(null)}>
              <X size={12} /> Back to grid
            </button>
            <StreamTile camera={focus} big clock={clock} proxyUrl={proxyHlsUrl(focus)} />
          </div>
        ) : (
          <div className={`flex-1 grid gap-2 ${GRID_CLASS[layout]}`} style={{ alignContent: "start" }}>
            {/* 300ms/tile stagger: the backend's own upstream semaphore
                (sentinel.py, concurrency=2) already protects the Cloudflare-
                facing egress IP, so this only needs to avoid bunching inbound
                connection opens — 1200ms added ~3.6s of pure artificial delay
                to the last tile in a 2x2 grid. */}
            {shown.map((c, i) => (
              <StreamTile key={c.id} camera={c} clock={clock}
                onExpand={() => setFocus(c)} proxyUrl={proxyHlsUrl(c)}
                startDelayMs={i * 300} />
            ))}
            {shown.length === 0 && (
              <div className="card col-span-full p-16 flex flex-col items-center gap-3 text-slate-600">
                <MonitorPlay size={36} />
                <div className="text-sm">Select cameras from the sidebar to start streaming</div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

