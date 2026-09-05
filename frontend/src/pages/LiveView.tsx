import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import {
  MonitorPlay, Maximize2, WifiOff, Loader2, Grid2X2, Grid3X3,
  LayoutGrid, Search, X, ExternalLink, Copy, Check,
} from "lucide-react";
import { api, formatTime } from "../lib/api";

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
const SENTINEL_PORTAL = "https://live.sentinelgujarat.in";

interface Camera {
  id: number; external_id: string | null; name: string;
  city: string | null; status: string; stream_url: string | null;
  rtsp_url: string | null; whep_url: string | null;
  resolution: string | null; analytics_tier: string;
}

const LAYOUTS = { "2×2": 4, "3×3": 9, "4×4": 16 } as const;
type LayoutKey = keyof typeof LAYOUTS;

function useBackoff(initial = 2000, cap = 30000) {
  const delay = useRef(initial);
  return {
    next: () => { const d = delay.current; delay.current = Math.min(delay.current * 2, cap); return d; },
    reset: () => { delay.current = initial; },
  };
}

const proxyHlsUrl = (cam: Camera): string | null => {
  if (!cam.external_id) return null;
  return `${API_BASE}/api/v1/sentinel/hls/${cam.external_id}/index.m3u8`;
};

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

type TileState = "loading" | "playing" | "error" | "no-stream";

function StreamTile({ camera, big, clock, onExpand, proxyUrl, startDelayMs = 0 }: {
  camera: Camera; big?: boolean; clock: Date; onExpand?: () => void;
  proxyUrl: string | null; startDelayMs?: number;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoff = useBackoff();
  const hlsUrl = proxyUrl ?? camera.stream_url;
  const [state, setState] = useState<TileState>(hlsUrl ? "loading" : "no-stream");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!hlsUrl) { setState("no-stream"); return; }
    const url = hlsUrl;

    function attach() {
      if (!videoRef.current) return;
      setState("loading");

      if (Hls.isSupported()) {
        const hls = new Hls({
          enableWorker: true, lowLatencyMode: false, maxBufferLength: 12, maxMaxBufferLength: 30,
          // Measured directly against the upstream CDN (deliberate, spaced
          // curls, not a load test): connect/TLS/auth is fast (~2.7-3.3s
          // TTFB), but body transfer crawls at roughly 4-25 KB/s regardless
          // of file size — a 215KB playlist took 48.9s total, a 532KB
          // segment took up to 36s. That is a genuine third-party throughput
          // ceiling (Cloudflare-fronted), not a queueing artifact of our own
          // proxy — its own concurrency gate logged 0ms wait on every one of
          // these. hls.js's old defaults (20s manifest / 30s fragment) are
          // shorter than fetches that are genuinely still going to succeed,
          // so it was giving up and tearing down/rebuilding the player mid-
          // fetch — that abandon-and-retry-storm, not the CDN itself, is
          // what produced "camera hangs, then comes back" for the operator.
          // Retries are cheap here regardless: the backend coalesces
          // concurrent identical-URL fetches, so a retry against a fetch
          // that's still in flight rides the same request instead of
          // starting a second one.
          manifestLoadingTimeOut: 60000,
          manifestLoadingMaxRetry: 3,
          fragLoadingTimeOut: 60000,
          fragLoadingMaxRetry: 3,
        });
        hlsRef.current = hls;

        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          backoff.reset();
          videoRef.current?.play().catch(() => undefined);
          setState("playing");
        });

        hls.on(Hls.Events.ERROR, (_evt, data) => {
          if (!data.fatal) return;
          hls.destroy(); hlsRef.current = null;
          setState("error");
          retryTimer.current = setTimeout(attach, backoff.next());
        });

        hls.on(Hls.Events.FRAG_PARSING_INIT_SEGMENT, () => {
          console.debug(`[hls] ${camera.external_id} — init segment parsed`);
        });

        hls.loadSource(url);
        hls.attachMedia(videoRef.current);
      } else if (videoRef.current.canPlayType("application/vnd.apple.mpegurl")) {
        videoRef.current.src = url;
        videoRef.current.play().catch(() => undefined);
        setState("playing");
        videoRef.current.onerror = () => {
          setState("error");
          retryTimer.current = setTimeout(attach, backoff.next());
        };
      } else {
        setState("no-stream");
      }
    }

    // Stagger the first request. Opening every tile simultaneously sends a
    // burst from the backend's single egress IP, which Cloudflare answers with
    // 403s for most of the grid.
    if (startDelayMs > 0) {
      startTimer.current = setTimeout(attach, startDelayMs);
    } else {
      attach();
    }

    return () => {
      hlsRef.current?.destroy();
      hlsRef.current = null;
      if (retryTimer.current) clearTimeout(retryTimer.current);
      if (startTimer.current) clearTimeout(startTimer.current);
    };
  }, [hlsUrl, camera.external_id, startDelayMs]);

  const copyRtsp = () => {
    if (camera.rtsp_url) {
      navigator.clipboard.writeText(camera.rtsp_url).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
    }
  };

  return (
    <div className="video-tile group" onClick={() => !big && onExpand?.()}>
      {camera.stream_url && (
        <video ref={videoRef} className="absolute inset-0 w-full h-full object-cover" muted playsInline autoPlay />
      )}

      {/* Loading */}
      {state === "loading" && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60">
          <Loader2 size={big ? 40 : 22} className="animate-spin text-orange-400" />
        </div>
      )}

      {/* Error / reconnecting */}
      {state === "error" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 gap-2">
          <WifiOff size={big ? 36 : 20} className="text-red-500" />
          <span className="text-xs text-red-400">Reconnecting…</span>
          {big && (
            <a href={SENTINEL_PORTAL} target="_blank" rel="noopener noreferrer"
              className="text-[11px] text-orange-400 hover:underline flex items-center gap-1 mt-1">
              Open Sentinel Grid <ExternalLink size={10} />
            </a>
          )}
        </div>
      )}

      {/* No stream */}
      {state === "no-stream" && (
        <div className="absolute inset-0 bg-gradient-to-br from-control-950 to-control-800 flex items-center justify-center">
          <div className="text-center px-3">
            <MonitorPlay className="mx-auto text-slate-700 mb-2" size={big ? 40 : 20} />
            <div className={`text-slate-500 font-medium ${big ? "text-sm" : "text-[10px]"}`}>{camera.name}</div>
          </div>
        </div>
      )}

      {/* Top OSD bar */}
      <div className="absolute top-0 inset-x-0 h-8 bg-gradient-to-b from-black/80 to-transparent flex items-center px-2 gap-2 z-10">
        <div className={`w-1.5 h-1.5 rounded-full ${state === "playing" ? "bg-emerald-400 animate-pulse" : state === "error" ? "bg-red-500" : "bg-amber-500"}`} />
        <span className="font-mono text-[9px] text-slate-200 truncate flex-1">
          {(camera.external_id ?? "").toUpperCase()} · {camera.name}
        </span>
        <span className="font-mono text-[9px] text-red-400 shrink-0">● {formatTime(clock.toISOString())}</span>
      </div>

      {/* Bottom OSD bar */}
      <div className="absolute bottom-0 inset-x-0 h-7 bg-gradient-to-t from-black/80 to-transparent flex items-center px-2 gap-2 z-10">
        <span className={`text-[9px] font-semibold ${camera.analytics_tier === "A" ? "text-orange-400" : camera.analytics_tier === "B" ? "text-cyan-400" : "text-slate-500"}`}>
          Tier {camera.analytics_tier}
        </span>
        {state === "playing" && <span className="text-[9px] text-emerald-400 font-mono">● HLS LIVE</span>}
        {camera.resolution && <span className="text-[9px] text-slate-600 font-mono">{camera.resolution}</span>}
        {camera.city && <span className="text-[9px] text-slate-500 ml-auto truncate">{camera.city}</span>}
      </div>

      {/* Hover controls */}
      <div className="absolute top-8 right-1.5 flex flex-col gap-1 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
        {camera.rtsp_url && (
          <button onClick={(e) => { e.stopPropagation(); copyRtsp(); }}
            className="btn-icon w-6 h-6" title="Copy RTSP URL for AI inference">
            {copied ? <Check size={10} className="text-emerald-400" /> : <Copy size={10} />}
          </button>
        )}
        {onExpand && (
          <button onClick={(e) => { e.stopPropagation(); onExpand(); }}
            className="btn-icon w-6 h-6" title="Expand">
            <Maximize2 size={10} />
          </button>
        )}
      </div>
    </div>
  );
}
