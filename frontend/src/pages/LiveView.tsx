import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import {
  MonitorPlay,
  Maximize2,
  WifiOff,
  Loader2,
  ExternalLink,
  Grid3X3,
  Play,
} from "lucide-react";
import { api, formatTime } from "../lib/api";

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
const SENTINEL_PORTAL = "https://live.sentinelgujarat.in";

interface Camera {
  id: number;
  external_id: string | null;
  name: string;
  city: string | null;
  status: string;
  stream_url: string | null;    // HLS CDN (direct, requires browser auth)
  rtsp_url: string | null;
  whep_url: string | null;
  stream_protocol: string | null;
  resolution: string | null;
  analytics_tier: string;
}

const LAYOUTS = { "2x2": 4, "3x3": 9, "4x4": 16 } as const;
type LayoutKey = keyof typeof LAYOUTS;

const HLS_CDN = "https://cctv.corp8.cloud";

/** Exponential backoff helper — integration.txt §3: reconnect with backoff. */
function useBackoff(initial = 2000, cap = 30000) {
  const delay = useRef(initial);
  return {
    next: () => {
      const d = delay.current;
      delay.current = Math.min(delay.current * 2, cap);
      return d;
    },
    reset: () => { delay.current = initial; },
  };
}

export default function LiveView() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [layout, setLayout] = useState<LayoutKey>("3x3");
  const [clock, setClock] = useState(new Date());
  const [focus, setFocus] = useState<Camera | null>(null);

  useEffect(() => {
    // Only fetch Sentinel cameras (those with real stream_url)
    api<{ items: Camera[] }>("/cameras?limit=30&status=online")
      .then((r) => setCameras(r.items.filter(c => c.stream_url)))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const grid = LAYOUTS[layout];
  const shown = cameras.slice(0, grid);

  // Build the proxied HLS URL for a camera — goes through Render backend
  // which handles Sentinel auth server-side (no cross-origin cookie issue)
  const proxyHlsUrl = (cam: Camera): string | null => {
    if (!cam.external_id) return null;
    return `${API_BASE}/api/v1/sentinel/hls/${cam.external_id}/index.m3u8`;
  };

  return (
    <div className="space-y-4 max-w-[1400px]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Unified Live View</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Sentinel Grid — {cameras.length} live streams ·{" "}
            <a
              href={SENTINEL_PORTAL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-orange-400 hover:underline"
            >
              live.sentinelgujarat.in
            </a>
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(Object.keys(LAYOUTS) as LayoutKey[]).map((k) => (
            <button
              key={k}
              className={`btn ${layout === k ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setLayout(k)}
            >
              <Grid3X3 size={13} /> {k}
            </button>
          ))}
        </div>
      </div>

      {focus ? (
        <div className="card overflow-hidden relative">
          <button
            className="absolute top-3 right-3 z-20 btn-ghost text-xs"
            onClick={() => setFocus(null)}
          >
            ← Back to grid
          </button>
          <StreamTile camera={focus} big clock={clock} proxyHlsUrl={proxyHlsUrl(focus)} />
        </div>
      ) : (
        <div
          className={`grid gap-3 ${
            layout === "2x2"
              ? "grid-cols-1 md:grid-cols-2"
              : layout === "3x3"
              ? "grid-cols-2 md:grid-cols-3"
              : "grid-cols-2 md:grid-cols-4"
          }`}
        >
          {shown.map((c) => (
            <StreamTile
              key={c.id}
              camera={c}
              clock={clock}
              onExpand={() => setFocus(c)}
              proxyHlsUrl={proxyHlsUrl(c)}
            />
          ))}
          {shown.length === 0 && (
            <div className="card p-10 text-center text-sm text-slate-500 col-span-full">
              <MonitorPlay size={28} className="mx-auto mb-2 text-slate-600" />
              No online cameras found.
            </div>
          )}
        </div>
      )}

      <p className="text-[11px] text-slate-600">
        Streams proxied through the IVMS backend (authenticated to Sentinel Grid) ·
        RTSP: <code className="text-slate-500">rtsp://103.250.160.189:8554/stream/cam01</code> (TCP) ·
        Direct portal:{" "}
        <a href={SENTINEL_PORTAL} target="_blank" rel="noopener noreferrer" className="text-orange-400 hover:underline">
          live.sentinelgujarat.in
        </a>
      </p>
    </div>
  );
}

type TileState = "loading" | "playing" | "error" | "no-stream";

function StreamTile({
  camera,
  big,
  clock,
  onExpand,
  proxyHlsUrl,
}: {
  camera: Camera;
  big?: boolean;
  clock: Date;
  onExpand?: () => void;
  proxyHlsUrl: string | null;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoff = useBackoff();
  // Use the proxied URL first (backend handles auth), fallback to direct CDN
  const hlsUrl = proxyHlsUrl ?? camera.stream_url;
  const [state, setState] = useState<TileState>(hlsUrl ? "loading" : "no-stream");

  useEffect(() => {
    if (!hlsUrl) {
      setState("no-stream");
      return;
    }
    const url = hlsUrl;

    function attach() {
      if (!videoRef.current) return;
      setState("loading");

      if (Hls.isSupported()) {
        // hls.js path — Chrome, Firefox, Edge
        const hls = new Hls({
          enableWorker: true,
          lowLatencyMode: false,
          // integration.txt §3: PTS-driven timing, bounded buffer for dashboard
          maxBufferLength: 8,
          maxMaxBufferLength: 15,
        });
        hlsRef.current = hls;

        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          backoff.reset();
          videoRef.current?.play().catch(() => undefined);
          setState("playing");
        });

        // integration.txt §3: reconnect with backoff; never tight-loop.
        hls.on(Hls.Events.ERROR, (_evt, data) => {
          if (!data.fatal) return; // non-fatal: hls.js self-recovers
          hls.destroy();
          hlsRef.current = null;
          setState("error");
          const delay = backoff.next();
          retryTimer.current = setTimeout(attach, delay);
        });

        // integration.txt §3: log decoder warnings, do not treat as fatal.
        hls.on(Hls.Events.FRAG_PARSING_INIT_SEGMENT, () => {
          console.debug(`[hls] ${camera.external_id} — init segment parsed`);
        });

        hls.loadSource(url);
        hls.attachMedia(videoRef.current);
      } else if (videoRef.current.canPlayType("application/vnd.apple.mpegurl")) {
        // Native HLS path — Safari
        videoRef.current.src = url;
        videoRef.current.play().catch(() => undefined);
        setState("playing");

        videoRef.current.onerror = () => {
          setState("error");
          const delay = backoff.next();
          retryTimer.current = setTimeout(attach, delay);
        };
      } else {
        setState("no-stream");
      }
    }

    attach();

    return () => {
      hlsRef.current?.destroy();
      hlsRef.current = null;
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hlsUrl, camera.external_id]);

  const iconSize = big ? 40 : 22;

  return (
    <div
      className={`relative bg-black rounded-lg overflow-hidden border border-control-800 aspect-video`}
    >
      {/* Real HLS video element */}
      {camera.stream_url && (
        <video
          ref={videoRef}
          className="absolute inset-0 w-full h-full object-cover"
          muted
          playsInline
          autoPlay
        />
      )}

      {/* Loading / error overlays */}
      {state === "loading" && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/70">
          <Loader2 size={iconSize} className="animate-spin text-orange-400" />
        </div>
      )}

      {state === "error" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 gap-2">
          <WifiOff size={iconSize} className="text-red-500" />
          <span className="text-xs text-red-400">Reconnecting…</span>
          {big && (
            <a
              href={SENTINEL_PORTAL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[11px] text-orange-400 hover:underline flex items-center gap-1 mt-1"
            >
              Open Sentinel Grid <ExternalLink size={10} />
            </a>
          )}
        </div>
      )}

      {state === "no-stream" && (
        <div className="absolute inset-0 bg-[linear-gradient(135deg,#0b1120_0%,#1e293b_50%,#0b1120_100%)] flex items-center justify-center">
          <div className="text-center px-3">
            <MonitorPlay className="mx-auto text-slate-700 mb-2" size={iconSize} />
            <div className={`text-slate-500 font-medium ${big ? "text-sm" : "text-[11px]"}`}>
              {camera.name}
            </div>
            <div className="text-[10px] text-slate-600 mt-1">
              Departmental VMS — not on Sentinel Grid
            </div>
          </div>
        </div>
      )}

      {/* OSD overlay — top bar */}
      <div className="absolute top-1.5 left-2 right-2 flex justify-between items-center text-[10px] font-mono z-10">
        <span className="bg-black/70 px-1.5 py-0.5 rounded text-slate-200 truncate max-w-[70%]">
          {camera.external_id
            ? camera.external_id.toUpperCase()
            : `CAM-${String(camera.id).padStart(3, "0")}`}{" "}
          {camera.city ? `· ${camera.city}` : ""}
        </span>
        <span className="bg-black/70 px-1.5 py-0.5 rounded text-red-400">
          ● REC {formatTime(clock.toISOString())}
        </span>
      </div>

      {/* OSD overlay — bottom bar */}
      <div className="absolute bottom-1.5 left-2 right-8 flex items-center gap-2 text-[10px] font-mono text-slate-400 z-10">
        <span>{camera.resolution}</span>
        {camera.stream_url && (
          <span className="text-emerald-500">● HLS</span>
        )}
        {camera.analytics_tier && (
          <span className={`${camera.analytics_tier === "A" ? "text-orange-400" : camera.analytics_tier === "B" ? "text-sky-400" : "text-slate-500"}`}>
            Tier {camera.analytics_tier}
          </span>
        )}
      </div>

      {/* Expand + open-stream buttons */}
      <div className="absolute bottom-1.5 right-2 flex items-center gap-1 z-10">
        {camera.stream_url && (
          <a
            href={camera.stream_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-400 hover:text-white bg-black/50 rounded p-1"
            title="Open HLS stream in new tab"
          >
            <ExternalLink size={11} />
          </a>
        )}
        {onExpand && (
          <button
            onClick={onExpand}
            className="text-slate-400 hover:text-white bg-black/50 rounded p-1"
          >
            <Maximize2 size={11} />
          </button>
        )}
      </div>
    </div>
  );
}
