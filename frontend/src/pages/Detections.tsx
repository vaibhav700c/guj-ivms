import { useEffect, useState } from "react";
import { RefreshCw, ImageOff, ScanFace, Car as CarIcon, User } from "lucide-react";
import { api, formatDateTime } from "../lib/api";
import InlineError from "../components/InlineError";

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

interface DetectionEvent {
  id: number;
  camera_id: number;
  camera_name: string | null;
  event_type: string;
  track_id: string | null;
  confidence: number;
  bbox: { x: number; y: number; w: number; h: number } | null;
  timestamp: string;
  has_evidence_image: boolean;
}

interface Camera { id: number; external_id: string | null; name: string }

const TYPE_ICON: Record<string, React.ElementType> = {
  face: ScanFace, vehicle: CarIcon, person: User,
};
const TYPE_LABEL: Record<string, string> = {
  face: "Face", vehicle: "Vehicle", person: "Person",
};
const TYPE_COLOR: Record<string, string> = {
  face: "text-red-400 border-red-500/25 bg-red-500/10",
  vehicle: "text-emerald-400 border-emerald-500/25 bg-emerald-500/10",
  person: "text-orange-400 border-orange-500/25 bg-orange-500/10",
};

/**
 * Detection Viewer — every event card shows the real annotated frame: a
 * genuine OpenCV bounding box + class label + confidence, drawn by the edge
 * worker (analytics/worker.py::draw_detection_boxes) directly onto the pixels
 * the model ran inference on at the moment of detection. This is not a CSS
 * overlay computed from stored bbox coordinates — the box is baked into the
 * JPEG itself, so what you see here is exactly what the model saw and found.
 */
export default function Detections() {
  const [items, setItems] = useState<DetectionEvent[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [eventType, setEventType] = useState("");
  const [cameraId, setCameraId] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [onlyWithFrame, setOnlyWithFrame] = useState(true);

  const load = () => {
    setLoading(true);
    const params = new URLSearchParams({ limit: "60" });
    if (eventType) params.set("event_type", eventType);
    if (cameraId) params.set("camera_id", cameraId);
    api<{ total: number; items: DetectionEvent[] }>(`/analytics/events?${params}`)
      .then((r) => { setItems(r.items); setError(null); })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => { setLoading(false); setLoadedOnce(true); });
  };

  useEffect(() => {
    api<{ items: Camera[] }>("/cameras?limit=200").then((r) => setCameras(r.items)).catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
    if (!autoRefresh) return;
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventType, cameraId, autoRefresh]);

  const shown = onlyWithFrame ? items.filter((i) => i.has_evidence_image) : items;

  return (
    <div className="space-y-4 max-w-[1400px]">
      <div className="page-header">
        <div>
          <h1 className="page-title">Detection Viewer</h1>
          <p className="page-subtitle">
            Real bounding boxes drawn by the edge worker (OpenCV) on the actual detection frame — not a mockup.
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={onlyWithFrame} onChange={(e) => setOnlyWithFrame(e.target.checked)} />
            Only with frame
          </label>
          <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            Auto-refresh
          </label>
          <button className="btn-ghost text-xs" onClick={load} disabled={loading}>
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>
      </div>

      <div className="card p-3 flex flex-wrap gap-3">
        <select className="input" value={eventType} onChange={(e) => setEventType(e.target.value)}>
          <option value="">All types</option>
          <option value="vehicle">Vehicle</option>
          <option value="person">Person</option>
          <option value="face">Face</option>
        </select>
        <select className="input" value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
          <option value="">All cameras</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>{c.external_id ? `${c.external_id} · ` : ""}{c.name}</option>
          ))}
        </select>
      </div>

      {error && <InlineError message={error} onRetry={load} onDismiss={() => setError(null)} />}

      {shown.length === 0 && loadedOnce && !error && (
        <div className="card p-10 text-center text-sm text-slate-500">
          No detections {onlyWithFrame ? "with a recorded frame " : ""}match these filters yet.
          {onlyWithFrame && (
            <div className="mt-1 text-xs text-slate-600">
              Try unchecking "Only with frame" — the demo simulator generates events without an image;
              a real detection frame only exists for events produced by the actual edge worker
              (analytics/worker.py or the Investigate page's local control server).
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {shown.map((d) => {
          const Icon = TYPE_ICON[d.event_type] ?? CarIcon;
          return (
            <div key={d.id} className="card overflow-hidden">
              <div className="relative aspect-video bg-control-850 flex items-center justify-center">
                {d.has_evidence_image ? (
                  <img
                    src={`${API_BASE}/api/v1/analytics/events/${d.id}/evidence`}
                    alt={`${d.event_type} detection`}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex flex-col items-center gap-1 text-slate-700">
                    <ImageOff size={20} />
                    <span className="text-[10px]">no frame recorded</span>
                  </div>
                )}
                <span className={`absolute top-2 left-2 badge border ${TYPE_COLOR[d.event_type] ?? ""}`}>
                  <Icon size={11} className="inline mr-1" />{TYPE_LABEL[d.event_type] ?? d.event_type}
                </span>
                <span className="absolute top-2 right-2 badge bg-black/60 text-white border border-white/10 font-mono">
                  {(d.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div className="p-2.5 text-xs">
                <div className="text-slate-300 truncate">{d.camera_name ?? `Camera #${d.camera_id}`}</div>
                <div className="text-[10px] text-slate-600 font-mono mt-0.5">{formatDateTime(d.timestamp)}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
