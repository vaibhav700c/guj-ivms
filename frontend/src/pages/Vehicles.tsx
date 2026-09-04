import { useEffect, useRef, useState } from "react";
import { Search, Route, MapPin, Clock, Gauge, Car, Camera as CameraIcon, ImageOff, ShieldQuestion } from "lucide-react";
import { MapContainer, TileLayer, Marker, Polyline, CircleMarker, Popup } from "react-leaflet";
import { api, formatDateTime, snapshotUrl } from "../lib/api";

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

// ── Snapshot thumbnails: lazy, capped-concurrency, never a broken-image icon ──
// The /feeds/{id}/snapshot endpoint is slow, rate-limited (1 real capture per
// camera per 8s server-side) and frequently fails upstream (502/503/504) until
// Sentinel CDN credentials are configured. So we only ever request it once a
// thumbnail scrolls into view, cap how many load at once, and fall back to a
// neutral placeholder on any error — never a browser broken-image icon.
const MAX_CONCURRENT_SNAPSHOTS = 3;
let activeSnapshotLoads = 0;
const snapshotWaiters: (() => void)[] = [];

function acquireSnapshotSlot(): Promise<() => void> {
  return new Promise((resolve) => {
    const tryAcquire = () => {
      if (activeSnapshotLoads < MAX_CONCURRENT_SNAPSHOTS) {
        activeSnapshotLoads++;
        let released = false;
        resolve(() => {
          if (released) return;
          released = true;
          activeSnapshotLoads--;
          const next = snapshotWaiters.shift();
          if (next) next();
        });
      } else {
        snapshotWaiters.push(tryAcquire);
      }
    };
    tryAcquire();
  });
}

function SnapshotThumb({ cameraId, eventId, hasEvidence, className }: {
  cameraId: number; eventId?: number; hasEvidence?: boolean; className?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const releaseRef = useRef<(() => void) | null>(null);
  const [visible, setVisible] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const [status, setStatus] = useState<"pending" | "loading" | "ready" | "error">("pending");

  // Only start trying once the thumbnail is actually scrolled near the viewport.
  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          obs.disconnect();
        }
      },
      { rootMargin: "150px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // A real evidence frame (the actual detection frame, captured by the edge
  // worker at match time) always takes priority over a generic live camera
  // snapshot — the two are not interchangeable: the live snapshot shows
  // whatever is on that camera *right now*, unrelated to this sighting's
  // actual timestamp/vehicle. Only fall back to it when no evidence exists.
  const isRealEvidence = Boolean(hasEvidence && eventId);
  useEffect(() => {
    if (!visible) return;
    const url = isRealEvidence
      ? `${API_BASE}/api/v1/vehicles/events/${eventId}/evidence`
      : snapshotUrl(cameraId);
    if (!url) {
      setStatus("error");
      return;
    }
    let cancelled = false;
    setStatus("loading");
    acquireSnapshotSlot().then((release) => {
      if (cancelled) {
        release();
        return;
      }
      releaseRef.current = release;
      setSrc(url);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, cameraId, eventId, isRealEvidence]);

  const finish = (ok: boolean) => {
    setStatus(ok ? "ready" : "error");
    releaseRef.current?.();
    releaseRef.current = null;
  };

  return (
    <div
      ref={hostRef}
      className={`relative shrink-0 overflow-hidden rounded-lg bg-control-850 border border-control-800/60 ${className ?? "w-14 h-10"}`}
      title={status === "error" ? "No frame available" : isRealEvidence ? "Real detection frame" : "Live camera snapshot (no detection frame recorded for this sighting)"}
    >
      {src && status !== "error" && (
        <img
          src={src}
          alt=""
          loading="lazy"
          className={`w-full h-full object-cover transition-opacity ${status === "ready" ? "opacity-100" : "opacity-0"}`}
          onLoad={() => finish(true)}
          onError={() => finish(false)}
        />
      )}
      {status === "loading" && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-3 h-3 rounded-full border-2 border-slate-600 border-t-orange-500 animate-spin" />
        </div>
      )}
      {(status === "pending" || status === "error") && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 text-slate-700">
          {status === "error" ? <ImageOff size={13} /> : <CameraIcon size={13} />}
          {status === "error" && <span className="text-[8px] text-slate-600 leading-none">no frame</span>}
        </div>
      )}
    </div>
  );
}

interface Journey {
  plate: string;
  registry: Record<string, string> | null;
  sightings_count: number;
  total_distance_km: number;
  cities_visited: string[];
  sightings: {
    event_id: number;
    camera_id: number;
    camera_name: string | null;
    lat: number | null;
    lng: number | null;
    city: string | null;
    timestamp: string;
    direction: string | null;
    confidence: number;
    has_evidence_image?: boolean;
    vehicle_type: string | null;
    vehicle_color: string | null;
  }[];
  legs: {
    from_camera: string | null;
    to_camera: string | null;
    distance_km: number;
    elapsed_min: number;
    avg_speed_kmph: number | null;
  }[];
  probable_matches?: {
    plate_text: string;
    similarity: number;
    camera_name: string | null;
    lat: number | null;
    lng: number | null;
    city: string | null;
    timestamp: string;
    confidence: number;
  }[];
  probable_reid_matches?: {
    camera_id: number;
    camera_name: string | null;
    lat: number | null;
    lng: number | null;
    city: string | null;
    timestamp: string;
    similarity: number;
    matched_from_camera: string | null;
    matched_from_timestamp: string;
  }[];
}

const DEFAULT_CENTER: [number, number] = [22.6, 71.6];

export default function Vehicles() {
  const [plate, setPlate] = useState("GJ 01 AB 1234");
  const [journey, setJourney] = useState<Journey | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [step, setStep] = useState(0); // replay progress

  const search = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setLoading(true);
    setError("");
    setJourney(null);
    setStep(0);
    try {
      const data = await api<Journey>(`/vehicles/search/${encodeURIComponent(plate)}`);
      setJourney(data);
      if (data.sightings_count === 0) setError("No ANPR sightings recorded for this plate yet.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setLoading(false);
    }
  };

  const shown = journey ? journey.sightings.slice(0, Math.max(step, 1)) : [];
  const last = shown[shown.length - 1];
  const center: [number, number] = last && last.lat && last.lng ? [last.lat, last.lng] : DEFAULT_CENTER;

  return (
    <div className="space-y-4 max-w-[1400px]">
      <div>
        <h1 className="text-xl font-bold">Vehicle Search &amp; Journey Reconstruction</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          Cross-camera plate matching → timestamped route replay (plan §7 / §20.2 test scenario)
        </p>
      </div>

      <form onSubmit={search} className="card p-4 flex gap-3">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-8 font-mono uppercase" placeholder="Enter plate e.g. GJ 01 AB 1234"
            value={plate} onChange={(e) => setPlate(e.target.value)} />
        </div>
        <button className="btn-primary" disabled={loading}>
          {loading ? "Searching…" : "Reconstruct Journey"}
        </button>
      </form>

      {error && (
        <div className="card p-4 text-sm text-slate-400">{error}</div>
      )}

      {journey && journey.sightings_count > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Summary */}
          <div className="card p-4 lg:col-span-1 space-y-3">
            <div className="font-mono text-lg text-orange-400">{journey.plate}</div>
            {journey.registry && (
              <div className="text-xs space-y-1 text-slate-400">
                <div className="font-semibold text-slate-300 mb-1 flex items-center gap-1"><Car size={12} /> VAHAN record</div>
                <div>{journey.registry.maker} {journey.registry.model}</div>
                <div>{journey.registry.color} · {journey.registry.vehicle_class}</div>
                <div>Owner: {journey.registry.owner_name}</div>
                <div>RTO: {journey.registry.rto_name}</div>
              </div>
            )}
            <div className="text-xs space-y-1.5 text-slate-300 border-t border-control-800 pt-3">
              <div className="flex items-center gap-2"><Route size={13} className="text-orange-400" /> {journey.sightings_count} sightings</div>
              <div className="flex items-center gap-2"><MapPin size={13} className="text-orange-400" /> {journey.total_distance_km} km covered</div>
              <div className="flex items-center gap-2"><Clock size={13} className="text-orange-400" /> {journey.cities_visited.join(" → ") || "—"}</div>
            </div>
            <button className="btn-primary w-full justify-center"
              onClick={() => setStep((s) => (s >= journey.sightings.length ? 1 : s + 1))}>
              ▶ Replay next sighting ({step}/{journey.sightings.length})
            </button>
            {journey.legs.slice(Math.max(0, step - 1), step).map((l, i) => (
              <div key={i} className="text-[11px] bg-control-850 rounded-lg p-2 text-slate-400">
                <div>{l.from_camera} → {l.to_camera}</div>
                <div className="flex items-center gap-2 mt-1">
                  <Gauge size={11} /> {l.distance_km} km in {l.elapsed_min} min
                  {l.avg_speed_kmph ? ` · ~${l.avg_speed_kmph} km/h` : ""}
                </div>
              </div>
            ))}
          </div>

          {/* Map */}
          <div className="card overflow-hidden lg:col-span-4 min-h-[480px]">
            <MapContainer center={center} zoom={7} className="h-[480px] w-full">
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              {/* Full route (dim) */}
              <Polyline
                positions={journey.sightings.filter((s) => s.lat && s.lng).map((s) => [s.lat!, s.lng!] as [number, number])}
                pathOptions={{ color: "#475569", weight: 2, dashArray: "4 6" }}
              />
              {/* Replay progress (bright) */}
              {shown.length > 1 && (
                <Polyline
                  positions={shown.filter((s) => s.lat && s.lng).map((s) => [s.lat!, s.lng!] as [number, number])}
                  pathOptions={{ color: "#f97316", weight: 3.5 }}
                />
              )}
              {journey.sightings.map((s, i) =>
                s.lat && s.lng ? (
                  <CircleMarker
                    key={s.event_id}
                    center={[s.lat, s.lng]}
                    radius={i < step ? 7 : 4}
                    pathOptions={{
                      color: i < step ? "#f97316" : "#64748b",
                      fillColor: i < step ? "#fdba74" : "#334155",
                      fillOpacity: 0.9,
                    }}
                  >
                    <Popup>
                      <div className="text-xs space-y-1.5">
                        <SnapshotThumb cameraId={s.camera_id} eventId={s.event_id} hasEvidence={s.has_evidence_image} className="w-40 h-24" />
                        <div className="font-semibold">{s.camera_name}</div>
                        <div className="font-mono text-[10px]">{formatDateTime(s.timestamp)}</div>
                        <div>dir: {s.direction ?? "—"} · conf {(s.confidence * 100).toFixed(0)}%</div>
                      </div>
                    </Popup>
                  </CircleMarker>
                ) : null
              )}
              {last && last.lat && last.lng && (
                <Marker position={[last.lat, last.lng]}>
                  <Popup>
                    <div className="text-xs font-semibold">Latest: {last.camera_name}</div>
                  </Popup>
                </Marker>
              )}
            </MapContainer>
          </div>

          {/* Timeline */}
          <div className="card lg:col-span-5">
            <div className="card-header text-sm font-semibold">Sighting Timeline</div>
            <div className="divide-y divide-control-800/60 max-h-72 overflow-y-auto">
              {journey.sightings.map((s, i) => (
                <div key={s.event_id}
                  className={`px-4 py-2.5 flex items-center gap-3 ${i < step ? "" : "opacity-50"}`}>
                  <div className={`w-2.5 h-2.5 rounded-full ${i < step ? "bg-orange-500" : "bg-control-700"}`} />
                  <SnapshotThumb cameraId={s.camera_id} eventId={s.event_id} hasEvidence={s.has_evidence_image} className="w-14 h-10" />
                  <div className="w-44 font-mono text-xs text-slate-400">{formatDateTime(s.timestamp)}</div>
                  <div className="flex-1 text-sm text-slate-300">{s.camera_name}</div>
                  <div className="text-xs text-slate-500 capitalize">{s.vehicle_type} · {s.direction}</div>
                  <div className="font-mono text-xs text-slate-500">{(s.confidence * 100).toFixed(0)}%</div>
                </div>
              ))}
            </div>
          </div>

          {/* Probable matches — OCR-tolerant fuzzy plate text, plan §20.2 step 5 */}
          {journey.probable_matches && journey.probable_matches.length > 0 && (
            <div className="card lg:col-span-5 border-amber-500/20">
              <div className="card-header text-sm font-semibold flex items-center gap-2 text-amber-400">
                <ShieldQuestion size={14} />
                Probable Matches — Unconfirmed (similar plate text, possible OCR misread)
              </div>
              <div className="divide-y divide-control-800/60 max-h-64 overflow-y-auto">
                {journey.probable_matches.map((m, i) => (
                  <div key={i} className="px-4 py-2.5 flex items-center gap-3 bg-amber-500/[0.03]">
                    <div className="w-2.5 h-2.5 rounded-full bg-amber-500/70 shrink-0" />
                    <div className="w-44 font-mono text-xs text-slate-400">{formatDateTime(m.timestamp)}</div>
                    <div className="flex-1 text-sm text-slate-300">
                      <span className="font-mono text-amber-300">{m.plate_text}</span>
                      <span className="text-slate-500"> · {m.camera_name ?? "—"}</span>
                      {m.city && <span className="text-slate-600"> ({m.city})</span>}
                    </div>
                    <div className="badge bg-amber-500/15 text-amber-400 border border-amber-500/25">
                      {(m.similarity * 100).toFixed(0)}% similarity
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Real cross-camera vehicle ReID — plan §7.2 Method 2 / Key Differentiator #3.
              For cameras where ANPR is known to be impossible (see the capability
              audit — plate_readable: false), appearance (HSV color histogram) is the
              only correlation signal available. */}
          {journey.probable_reid_matches && journey.probable_reid_matches.length > 0 && (
            <div className="card lg:col-span-5 border-cyan-500/20">
              <div className="card-header text-sm font-semibold flex items-center gap-2 text-cyan-400">
                <ShieldQuestion size={14} />
                Probable Matches — Unconfirmed (appearance ReID, camera cannot read plates)
              </div>
              <div className="divide-y divide-control-800/60 max-h-64 overflow-y-auto">
                {journey.probable_reid_matches.map((m, i) => (
                  <div key={i} className="px-4 py-2.5 flex items-center gap-3 bg-cyan-500/[0.03]">
                    <div className="w-2.5 h-2.5 rounded-full bg-cyan-500/70 shrink-0" />
                    <div className="w-44 font-mono text-xs text-slate-400">{formatDateTime(m.timestamp)}</div>
                    <div className="flex-1 text-sm text-slate-300">
                      <span className="text-slate-500">{m.camera_name ?? "—"}</span>
                      {m.city && <span className="text-slate-600"> ({m.city})</span>}
                      <span className="text-[10px] text-slate-600 block">
                        matched from {m.matched_from_camera ?? "—"} at {formatDateTime(m.matched_from_timestamp)}
                      </span>
                    </div>
                    <div className="badge bg-cyan-500/15 text-cyan-400 border border-cyan-500/25">
                      {(m.similarity * 100).toFixed(0)}% appearance match
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
