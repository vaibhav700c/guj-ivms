import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import {
  Maximize2, WifiOff, Loader2, MonitorPlay, ExternalLink, Copy, Check,
} from "lucide-react";
import { formatTime } from "../lib/api";

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";
const SENTINEL_PORTAL = "https://live.sentinelgujarat.in";

export interface StreamCamera {
  id: number; external_id: string | null; name: string;
  city: string | null; status: string; stream_url: string | null;
  rtsp_url: string | null; whep_url?: string | null;
  resolution: string | null; analytics_tier: string;
}

export function proxyHlsUrl(cam: StreamCamera): string | null {
  if (!cam.external_id) return null;
  return `${API_BASE}/api/v1/sentinel/hls/${cam.external_id}/index.m3u8`;
}

export function useBackoff(initial = 2000, cap = 30000) {
  const delay = useRef(initial);
  return {
    next: () => { const d = delay.current; delay.current = Math.min(delay.current * 2, cap); return d; },
    reset: () => { delay.current = initial; },
  };
}

export type TileState = "loading" | "playing" | "error" | "no-stream";

/**
 * A single real HLS video tile — the actual Sentinel Grid feed, decoded and
 * played client-side (not a snapshot, not a placeholder). Shared between
 * LiveView (the full video wall) and Investigate (live footage for the
 * camera(s) a monitoring job is actually watching).
 */
export default function StreamTile({ camera, big, clock, onExpand, proxyUrl, startDelayMs = 0, compact }: {
  camera: StreamCamera; big?: boolean; clock: Date; onExpand?: () => void;
  proxyUrl: string | null; startDelayMs?: number; compact?: boolean;
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
          // See LiveView/StreamTile history: the upstream CDN's own body-
          // transfer throughput (not our proxy's queueing — it logs 0ms gate
          // wait) can legitimately take up to ~60s for a cold segment. Shorter
          // timeouts tear the player down mid-fetch and retry-storm instead of
          // just waiting, which is what "camera hangs then comes back" was.
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

      {state === "loading" && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60">
          <Loader2 size={big ? 40 : compact ? 16 : 22} className="animate-spin text-orange-400" />
        </div>
      )}

      {state === "error" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 gap-2">
          <WifiOff size={big ? 36 : compact ? 14 : 20} className="text-red-500" />
          {!compact && <span className="text-xs text-red-400">Reconnecting…</span>}
          {big && (
            <a href={SENTINEL_PORTAL} target="_blank" rel="noopener noreferrer"
              className="text-[11px] text-orange-400 hover:underline flex items-center gap-1 mt-1">
              Open Sentinel Grid <ExternalLink size={10} />
            </a>
          )}
        </div>
      )}

      {state === "no-stream" && (
        <div className="absolute inset-0 bg-gradient-to-br from-control-950 to-control-800 flex items-center justify-center">
          <div className="text-center px-3">
            <MonitorPlay className="mx-auto text-slate-700 mb-2" size={big ? 40 : compact ? 16 : 20} />
            {!compact && <div className={`text-slate-500 font-medium ${big ? "text-sm" : "text-[10px]"}`}>{camera.name}</div>}
          </div>
        </div>
      )}

      {/* Top OSD bar */}
      <div className="absolute top-0 inset-x-0 h-8 bg-gradient-to-b from-black/80 to-transparent flex items-center px-2 gap-2 z-10">
        <div className={`w-1.5 h-1.5 rounded-full ${state === "playing" ? "bg-emerald-400 animate-pulse" : state === "error" ? "bg-red-500" : "bg-amber-500"}`} />
        <span className="font-mono text-[9px] text-slate-200 truncate flex-1">
          {(camera.external_id ?? "").toUpperCase()} · {camera.name}
        </span>
        {!compact && <span className="font-mono text-[9px] text-red-400 shrink-0">● {formatTime(clock.toISOString())}</span>}
      </div>

      {!compact && (
        <div className="absolute bottom-0 inset-x-0 h-7 bg-gradient-to-t from-black/80 to-transparent flex items-center px-2 gap-2 z-10">
          <span className={`text-[9px] font-semibold ${camera.analytics_tier === "A" ? "text-orange-400" : camera.analytics_tier === "B" ? "text-cyan-400" : "text-slate-500"}`}>
            Tier {camera.analytics_tier}
          </span>
          {state === "playing" && <span className="text-[9px] text-emerald-400 font-mono">● HLS LIVE</span>}
          {camera.resolution && <span className="text-[9px] text-slate-600 font-mono">{camera.resolution}</span>}
          {camera.city && <span className="text-[9px] text-slate-500 ml-auto truncate">{camera.city}</span>}
        </div>
      )}

      <div className="absolute top-8 right-1.5 flex flex-col gap-1 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
        {camera.rtsp_url && !compact && (
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
