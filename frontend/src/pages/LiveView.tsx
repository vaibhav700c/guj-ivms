import { useEffect, useState } from "react";
import { MonitorPlay, Maximize2, Grid3X3 } from "lucide-react";
import { api, formatTime } from "../lib/api";

interface Camera {
  id: number;
  name: string;
  city: string | null;
  status: string;
  stream_url: string | null;
  stream_protocol: string | null;
  resolution: string | null;
}

const LAYOUTS = { "2x2": 4, "3x3": 9, "4x4": 16 } as const;
type LayoutKey = keyof typeof LAYOUTS;

export default function LiveView() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [layout, setLayout] = useState<LayoutKey>("3x3");
  const [clock, setClock] = useState(new Date());
  const [focus, setFocus] = useState<Camera | null>(null);

  useEffect(() => {
    api<{ items: Camera[] }>("/cameras?limit=16&status=online")
      .then((r) => setCameras(r.items))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const grid = LAYOUTS[layout];
  const shown = cameras.slice(0, grid);

  return (
    <div className="space-y-4 max-w-[1400px]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Unified Live View</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Model 2 — RTSP/WebRTC/HLS aggregation grid · MediaMTX re-publish in full deployment
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(Object.keys(LAYOUTS) as LayoutKey[]).map((k) => (
            <button key={k} className={`btn ${layout === k ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setLayout(k)}>
              <Grid3X3 size={13} /> {k}
            </button>
          ))}
        </div>
      </div>

      {focus ? (
        <div className="card overflow-hidden relative">
          <button className="absolute top-3 right-3 z-10 btn-ghost text-xs"
            onClick={() => setFocus(null)}>← Back to grid</button>
          <StreamTile camera={focus} big clock={clock} />
        </div>
      ) : (
        <div className={`grid gap-3 ${
          layout === "2x2" ? "grid-cols-1 md:grid-cols-2" :
          layout === "3x3" ? "grid-cols-2 md:grid-cols-3" : "grid-cols-2 md:grid-cols-4"}`}>
          {shown.map((c) => (
            <StreamTile key={c.id} camera={c} clock={clock}
              onExpand={() => setFocus(c)} />
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
        Note: browser grids render the simulated feed tile. In the full stack (docker-compose),
        MediaMTX converts each RTSP source to WebRTC/HLS and tiles play the live stream here.
      </p>
    </div>
  );
}

function StreamTile({ camera, big, clock, onExpand }: {
  camera: Camera;
  big?: boolean;
  clock: Date;
  onExpand?: () => void;
}) {
  return (
    <div className={`relative bg-black rounded-lg overflow-hidden border border-control-800 ${big ? "aspect-video" : "aspect-video"}`}>
      {/* Simulated feed placeholder */}
      <div className="absolute inset-0 bg-[linear-gradient(135deg,#0b1120_0%,#1e293b_50%,#0b1120_100%)] flex items-center justify-center">
        <div className="text-center">
          <MonitorPlay className="mx-auto text-slate-700 mb-2" size={big ? 40 : 22} />
          <div className={`text-slate-500 font-medium ${big ? "text-sm" : "text-[11px]"} px-2`}>{camera.name}</div>
          {big && camera.stream_url && (
            <div className="text-[10px] font-mono text-slate-600 mt-1">{camera.stream_url}</div>
          )}
        </div>
      </div>
      {/* OSD overlay */}
      <div className="absolute top-1.5 left-2 right-2 flex justify-between items-center text-[10px] font-mono">
        <span className="bg-black/60 px-1.5 py-0.5 rounded text-slate-200 truncate max-w-[70%]">
          CAM-{String(camera.id).padStart(3, "0")} {camera.city ? `· ${camera.city}` : ""}
        </span>
        <span className="bg-black/60 px-1.5 py-0.5 rounded text-red-400">● REC {formatTime(clock.toISOString())}</span>
      </div>
      <div className="absolute bottom-1.5 left-2 text-[10px] font-mono text-slate-400">
        {camera.resolution} · {camera.stream_protocol}
      </div>
      {onExpand && (
        <button onClick={onExpand}
          className="absolute bottom-1.5 right-2 text-slate-400 hover:text-white bg-black/50 rounded p-1">
          <Maximize2 size={12} />
        </button>
      )}
    </div>
  );
}
