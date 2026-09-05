import { useEffect, useRef, useState } from "react";
import {
  UserSearch, Car, Upload, Play, Square, RefreshCw, AlertTriangle,
  CheckCircle, Video, Radio, ExternalLink, ScanEye, ImageOff,
} from "lucide-react";
import { api, formatDateTime } from "../lib/api";
import InlineError from "../components/InlineError";
import StreamTile, { proxyHlsUrl, type StreamCamera } from "../components/StreamTile";
import Lightbox, { ExpandHint } from "../components/Lightbox";

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

/**
 * "Investigate" — the operator-facing bridge to the local edge pipeline
 * (analytics/control_server.py). This page runs entirely against a service
 * on the OPERATOR's OWN machine (http://localhost:8800 by default): the real
 * CV stack (YOLOv8 + InsightFace) needs ~2GB RAM and never runs on Render's
 * 512MB free tier (see CLAUDE.md). Fetches to localhost from this
 * https://guj-ivms.vercel.app page are not blocked as mixed content —
 * localhost is a spec'd "potentially trustworthy origin" — so this works
 * from the real deployed site as long as the operator has started
 * control_server.py on the machine they're viewing this page from.
 */

const CONTROL_BASE =
  (import.meta.env.VITE_CONTROL_SERVER_URL as string | undefined) || "http://localhost:8800";

type Camera = StreamCamera;

interface DetectionEvent {
  id: number; camera_id: number; event_type: string; confidence: number;
  timestamp: string; has_evidence_image: boolean;
}
interface HealthState {
  status: string;
  models: { yolo: boolean; anpr: boolean; face: boolean };
  jobs_running: number;
  cameras_active: number[];
}
interface JobCamera { camera_id: number; running: boolean; frames_processed: number; faces_matched: number; anpr_stats: Record<string, number> }
interface Job {
  job_id: string; mode: "face" | "plate"; target_entry_id: number; plate: string | null;
  camera_ids: number[]; started_at: number; status: string; cameras: JobCamera[];
}

async function localApi<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${CONTROL_BASE}${path}`, {
    ...options,
    headers: { ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...options.headers },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let detail = body;
    try { detail = JSON.parse(body).detail ?? body; } catch { /* not JSON */ }
    throw new Error(`${res.status}: ${detail || res.statusText}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

function CameraPicker({ cameras, selected, onChange }: {
  cameras: Camera[]; selected: number[]; onChange: (ids: number[]) => void;
}) {
  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter((c) => c !== id) : [...selected, id]);
  return (
    <div className="border border-control-800 rounded-lg max-h-40 overflow-y-auto divide-y divide-control-800/60">
      {cameras.length === 0 && (
        <div className="p-3 text-xs text-slate-600">No cameras yet — register one below, or use the Sentinel Grid cameras once loaded.</div>
      )}
      {cameras.map((c) => (
        <label key={c.id} className="flex items-center gap-2 px-3 py-1.5 text-xs cursor-pointer hover:bg-control-800/40">
          <input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggle(c.id)} />
          <span className="font-mono text-slate-500">{c.external_id ?? c.id}</span>
          <span className="text-slate-300 truncate">{c.name}</span>
        </label>
      ))}
    </div>
  );
}

const TYPE_BOX_COLOR: Record<string, string> = {
  vehicle: "border-emerald-500/60", person: "border-orange-500/60", face: "border-red-500/60",
};

/**
 * The real annotated detection frames for one camera, as the actual edge
 * pipeline produces them — a genuine OpenCV bounding box baked into the JPEG
 * at the moment of detection (analytics/worker.py::draw_detection_boxes),
 * not a mockup. Polls while its parent job is running so new detections
 * appear here within a few seconds of happening.
 */
function DetectionFeed({ cameraId, active }: { cameraId: number; active: boolean }) {
  const [events, setEvents] = useState<DetectionEvent[]>([]);
  const [enlarged, setEnlarged] = useState<DetectionEvent | null>(null);

  useEffect(() => {
    if (!active) return;
    const load = () => {
      api<{ items: DetectionEvent[] }>(`/analytics/events?camera_id=${cameraId}&source=edge_worker&limit=6`)
        .then((r) => setEvents(r.items.filter((e) => e.has_evidence_image)))
        .catch(() => undefined);
    };
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [cameraId, active]);

  if (events.length === 0) {
    return (
      <div className="flex items-center gap-1.5 text-[10px] text-slate-600 px-1 py-2">
        <ScanEye size={11} className="animate-pulse" /> Watching for a detection with a real frame…
      </div>
    );
  }

  return (
    <>
      <div className="flex gap-1.5 overflow-x-auto pb-0.5">
        {events.map((e) => (
          <div
            key={e.id}
            className={`relative shrink-0 w-16 h-11 rounded overflow-hidden bg-black/40 border-2 cursor-zoom-in group ${TYPE_BOX_COLOR[e.event_type] ?? "border-control-700"}`}
            onClick={() => setEnlarged(e)}
            title={`${e.event_type} · ${(e.confidence * 100).toFixed(0)}% · click to enlarge`}
          >
            <img
              src={`${API_BASE}/api/v1/analytics/events/${e.id}/evidence`}
              alt={e.event_type}
              loading="lazy"
              className="w-full h-full object-cover"
            />
            <ExpandHint />
          </div>
        ))}
      </div>
      {enlarged && (
        <Lightbox
          src={`${API_BASE}/api/v1/analytics/events/${enlarged.id}/evidence`}
          alt={enlarged.event_type}
          caption={`${enlarged.event_type} · ${(enlarged.confidence * 100).toFixed(0)}% · ${formatDateTime(enlarged.timestamp)}`}
          onClose={() => setEnlarged(null)}
        />
      )}
    </>
  );
}

/**
 * The live monitoring view for one job: the ACTUAL camera footage (real HLS,
 * same decode path as Live View) for every camera it's watching, each paired
 * with that camera's real-time detection feed. This is what makes "Start
 * Monitoring" visibly do something — before this, the only feedback was a
 * one-line frame counter.
 */
function JobMonitor({ job, cameras, clock }: { job: Job; cameras: Camera[]; clock: Date }) {
  const running = job.status === "running";
  const jobCams = job.camera_ids
    .map((id) => cameras.find((c) => c.id === id))
    .filter((c): c is Camera => Boolean(c));

  return (
    <div
      className={`rounded-xl border p-3 transition-all ${
        running ? "border-emerald-500/50 bg-emerald-500/[0.03] shadow-[0_0_0_1px_rgba(16,185,129,0.15)]" : "border-control-800 bg-control-850"
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
          {running && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />}
          {job.mode === "face" ? <UserSearch size={12} /> : <Car size={12} />}
          {job.mode === "face" ? `Person watchlist #${job.target_entry_id}` : `Plate ${job.plate}`}
          <span className={`badge ${running ? "badge-low" : "bg-slate-500/15 text-slate-400"}`}>{job.status}</span>
        </div>
      </div>

      {!running ? (
        // Stopped job: a plain summary, no live tiles — rendering real HLS
        // video for every past job (not just the running one) was itself a
        // bug caught here: it fires a burst of simultaneous cold Sentinel
        // fetches for cameras nobody is currently watching, which is exactly
        // the kind of load that trips Cloudflare's per-IP throttling.
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {job.cameras.map((c) => (
            <div key={c.camera_id} className="text-[10px] text-slate-500 font-mono">
              cam {c.camera_id}: {c.frames_processed}f
              {job.mode === "face" && `, ${c.faces_matched} match${c.faces_matched === 1 ? "" : "es"}`}
              {job.mode === "plate" && c.anpr_stats.pushed ? `, ${c.anpr_stats.pushed} plate(s)` : ""}
            </div>
          ))}
        </div>
      ) : jobCams.length === 0 ? (
        <div className="text-[11px] text-slate-600 flex items-center gap-1.5 py-2">
          <ImageOff size={12} /> None of this job's cameras are in the registry yet — frame counts only.
        </div>
      ) : (
        <div className={`grid gap-2 ${jobCams.length > 2 ? "grid-cols-2 md:grid-cols-3" : "grid-cols-1 md:grid-cols-2"}`}>
          {jobCams.map((cam, i) => {
            const stat = job.cameras.find((c) => c.camera_id === cam.id);
            return (
              <div key={cam.id} className="space-y-1">
                <div className="relative rounded-lg overflow-hidden border border-control-800/60" style={{ aspectRatio: "16/9" }}>
                  <StreamTile camera={cam} clock={clock} proxyUrl={proxyHlsUrl(cam)} startDelayMs={i * 250} compact />
                </div>
                <div className="flex items-center justify-between text-[9px] font-mono text-slate-600 px-0.5">
                  <span>{stat?.frames_processed ?? 0} frames analyzed</span>
                  {job.mode === "face" && <span>{stat?.faces_matched ?? 0} match{stat?.faces_matched === 1 ? "" : "es"}</span>}
                  {job.mode === "plate" && !!stat?.anpr_stats.pushed && <span>{stat.anpr_stats.pushed} plate(s)</span>}
                </div>
                <DetectionFeed cameraId={cam.id} active={running} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function Investigate() {
  const [health, setHealth] = useState<HealthState | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [tab, setTab] = useState<"person" | "vehicle">("person");
  const [clock, setClock] = useState(new Date());

  // Wanted-person form
  const [file, setFile] = useState<File | null>(null);
  const [identifier, setIdentifier] = useState("");
  const [severity, setSeverity] = useState("critical");
  const [personCams, setPersonCams] = useState<number[]>([]);
  const [personBusy, setPersonBusy] = useState(false);
  const [personError, setPersonError] = useState<string | null>(null);
  const [personResult, setPersonResult] = useState<string | null>(null);

  // Vehicle form
  const [plate, setPlate] = useState("");
  const [plateCams, setPlateCams] = useState<number[]>([]);
  const [plateBusy, setPlateBusy] = useState(false);
  const [plateError, setPlateError] = useState<string | null>(null);
  const [plateResult, setPlateResult] = useState<string | null>(null);

  // Register-local-camera form
  const [showRegister, setShowRegister] = useState(false);
  const [regName, setRegName] = useState("");
  const [regPath, setRegPath] = useState("");
  const [regError, setRegError] = useState<string | null>(null);
  const [regBusy, setRegBusy] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const refreshHealth = () => {
    localApi<HealthState>("/api/local/health")
      .then((h) => { setHealth(h); setHealthError(null); })
      .catch((e) => { setHealth(null); setHealthError(e instanceof Error ? e.message : String(e)); });
  };

  const refreshJobs = () => {
    localApi<{ jobs: Job[] }>("/api/local/monitor/status")
      .then((r) => setJobs(r.jobs))
      .catch(() => { /* control server unreachable — health banner already covers this */ });
  };

  const refreshCameras = () => {
    api<{ items: Camera[] }>("/cameras?limit=200")
      .then((r) => setCameras(r.items))
      .catch(() => { /* non-fatal — register-local still works without the list */ });
  };

  useEffect(() => {
    refreshHealth();
    refreshCameras();
    refreshJobs();
    const id = setInterval(() => { refreshHealth(); refreshJobs(); }, 4000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const connected = health?.status === "ok";

  const enrollAndStart = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !identifier.trim() || personCams.length === 0) return;
    setPersonBusy(true);
    setPersonError(null);
    setPersonResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("identifier", identifier.trim());
      form.append("severity", severity);
      const enrolled = await localApi<{ entry_id: number; embedding_dim: number; face_detect_confidence: number }>(
        "/api/local/watchlist/enroll-photo", { method: "POST", body: form }
      );
      await localApi<Job>("/api/local/monitor/start", {
        method: "POST",
        body: JSON.stringify({ mode: "face", entry_id: enrolled.entry_id, camera_ids: personCams }),
      });
      setPersonResult(
        `Enrolled "${identifier}" (${enrolled.embedding_dim}-d embedding, ` +
        `face detected at ${(enrolled.face_detect_confidence * 100).toFixed(0)}% confidence) — ` +
        `now monitoring ${personCams.length} camera(s). Matches appear on Live Alerts in real time.`
      );
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      refreshJobs();
    } catch (err) {
      setPersonError(err instanceof Error ? err.message : String(err));
    } finally {
      setPersonBusy(false);
    }
  };

  const startPlateWatch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!plate.trim() || plateCams.length === 0) return;
    setPlateBusy(true);
    setPlateError(null);
    setPlateResult(null);
    try {
      await localApi<Job>("/api/local/monitor/start", {
        method: "POST",
        body: JSON.stringify({ mode: "plate", plate: plate.trim(), camera_ids: plateCams }),
      });
      setPlateResult(`Watching ${plateCams.length} camera(s) for plate "${plate.trim()}" — matches appear on Live Alerts and the GIS map in real time.`);
      refreshJobs();
    } catch (err) {
      setPlateError(err instanceof Error ? err.message : String(err));
    } finally {
      setPlateBusy(false);
    }
  };

  const registerLocal = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!regName.trim() || !regPath.trim()) return;
    setRegBusy(true);
    setRegError(null);
    try {
      await localApi("/api/local/cameras/register-local", {
        method: "POST",
        body: JSON.stringify({ name: regName.trim(), video_path: regPath.trim() }),
      });
      setRegName(""); setRegPath(""); setShowRegister(false);
      refreshCameras();
    } catch (err) {
      setRegError(err instanceof Error ? err.message : String(err));
    } finally {
      setRegBusy(false);
    }
  };

  const stopJob = async (jobId: string) => {
    try {
      await localApi(`/api/local/monitor/${jobId}/stop`, { method: "POST" });
      refreshJobs();
    } catch { /* best-effort */ }
  };

  return (
    <div className="space-y-4 max-w-[1100px]">
      <div>
        <h1 className="text-xl font-bold flex items-center gap-2"><UserSearch size={20} className="text-orange-400" /> Investigate</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          Upload a wanted-person photo or enter a plate number, then run the real edge detection
          pipeline (YOLOv8 + InsightFace ArcFace + plate OCR) against live or local camera feeds.
        </p>
      </div>

      {/* Local control server connection status */}
      <div className={`card p-3 flex items-center justify-between ${connected ? "border-emerald-500/25" : "border-amber-500/25"}`}>
        <div className="flex items-center gap-2 text-xs">
          <Radio size={14} className={connected ? "text-emerald-400" : "text-amber-400"} />
          {connected ? (
            <span className="text-emerald-300">
              Local inference service connected — YOLOv8 {health!.models.yolo ? "✓" : "✗"} ·
              {" "}ANPR {health!.models.anpr ? "✓" : "✗"} · Face {health!.models.face ? "✓" : "✗"}
              {" "}· {health!.jobs_running} job(s) running
            </span>
          ) : (
            <span className="text-amber-300">
              Local inference service not reachable at <code className="font-mono">{CONTROL_BASE}</code>.
              Start it on this machine: <code className="font-mono">cd analytics && .venv/bin/uvicorn control_server:app --port 8800</code>
              {healthError && <span className="text-slate-500"> ({healthError})</span>}
            </span>
          )}
        </div>
        <button className="btn-icon" onClick={refreshHealth} title="Recheck"><RefreshCw size={13} /></button>
      </div>

      {!connected && (
        <InlineError message="Investigate requires the local inference service above — it never runs on Render (the ML stack needs ~2GB RAM, the free tier has 512MB). See docs/DEMO_SCRIPT.md for the one-time local setup." />
      )}

      {/* Local video/webcam registration */}
      <div className="card p-3">
        <button className="btn-ghost text-xs" onClick={() => setShowRegister(!showRegister)}>
          <Video size={13} /> Register a local video file or webcam as a camera
        </button>
        {showRegister && (
          <form onSubmit={registerLocal} className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2">
            <input className="input" placeholder="Camera name" value={regName} onChange={(e) => setRegName(e.target.value)} required />
            <input className="input" placeholder="/path/to/clip.mp4 or webcam index (0)" value={regPath} onChange={(e) => setRegPath(e.target.value)} required />
            <button className="btn-primary justify-center" disabled={regBusy}>{regBusy ? "Registering…" : "Register"}</button>
            {regError && <div className="col-span-full"><InlineError message={regError} onDismiss={() => setRegError(null)} /></div>}
            <p className="col-span-full text-[10px] text-slate-600">
              Demo clips are bundled at <code className="font-mono">analytics/demo_assets/</code> — e.g.
              {" "}<code className="font-mono">analytics/demo_assets/wanted_person_demo.mp4</code>.
            </p>
          </form>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        <button className={`btn-ghost text-xs ${tab === "person" ? "bg-control-800 text-white" : ""}`} onClick={() => setTab("person")}>
          <UserSearch size={13} /> Wanted Person
        </button>
        <button className={`btn-ghost text-xs ${tab === "vehicle" ? "bg-control-800 text-white" : ""}`} onClick={() => setTab("vehicle")}>
          <Car size={13} /> Vehicle Plate
        </button>
      </div>

      {tab === "person" && (
        <form onSubmit={enrollAndStart} className="card p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs text-slate-400">Reference photo</label>
              <label className="btn-ghost text-xs cursor-pointer w-fit">
                <Upload size={12} /> {file ? file.name : "Choose photo"}
                <input ref={fileInputRef} type="file" accept="image/*" className="hidden"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </label>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-slate-400">Identifier</label>
              <input className="input w-full" placeholder="e.g. Suspect — FIR/2026/AHD/012"
                value={identifier} onChange={(e) => setIdentifier(e.target.value)} required />
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">Severity</label>
            <select className="input" value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">Camera(s) to monitor</label>
            <CameraPicker cameras={cameras} selected={personCams} onChange={setPersonCams} />
          </div>
          {personError && <InlineError message={personError} onDismiss={() => setPersonError(null)} />}
          {personResult && (
            <div className="text-xs rounded-lg px-3 py-2 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-start gap-2">
              <CheckCircle size={14} className="shrink-0 mt-0.5" /> {personResult}
            </div>
          )}
          <button className="btn-primary" disabled={!connected || personBusy || !file || !identifier.trim() || personCams.length === 0}>
            <Play size={13} /> {personBusy ? "Enrolling & Starting…" : "Enroll & Start Monitoring"}
          </button>
        </form>
      )}

      {tab === "vehicle" && (
        <form onSubmit={startPlateWatch} className="card p-4 space-y-3">
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">Vehicle registration number</label>
            <input className="input w-full font-mono" placeholder="e.g. GJ 01 AB 1234"
              value={plate} onChange={(e) => setPlate(e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">Camera(s) to monitor</label>
            <CameraPicker cameras={cameras} selected={plateCams} onChange={setPlateCams} />
          </div>
          {plateError && <InlineError message={plateError} onDismiss={() => setPlateError(null)} />}
          {plateResult && (
            <div className="text-xs rounded-lg px-3 py-2 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-start gap-2">
              <CheckCircle size={14} className="shrink-0 mt-0.5" /> {plateResult}
            </div>
          )}
          <button className="btn-primary" disabled={!connected || plateBusy || !plate.trim() || plateCams.length === 0}>
            <Play size={13} /> {plateBusy ? "Starting…" : "Start Live Plate Watch"}
          </button>
        </form>
      )}

      {/* Active jobs — real live footage + real detection frames, not a status line */}
      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold flex items-center gap-2">
            Live Monitoring
            {jobs.some((j) => j.status === "running") && (
              <span className="text-[10px] font-normal px-2 py-0.5 rounded-full border border-emerald-500/30 text-emerald-400 bg-emerald-500/10 animate-pulse">
                ● ACTIVE
              </span>
            )}
          </div>
          <a href="/alerts" className="text-xs text-orange-400/80 hover:text-orange-400 flex items-center gap-1">
            View Live Alerts <ExternalLink size={11} />
          </a>
        </div>
        {jobs.length === 0 && (
          <div className="text-xs text-slate-600 py-6 text-center">
            No monitoring jobs running. Start one above — real camera footage and detections will appear here.
          </div>
        )}
        <div className="space-y-3">
          {jobs.map((j) => (
            <div key={j.job_id}>
              <JobMonitor job={j} cameras={cameras} clock={clock} />
              {j.status === "running" && (
                <div className="flex justify-end mt-1.5">
                  <button className="btn-ghost text-xs" onClick={() => stopJob(j.job_id)}><Square size={11} /> Stop</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="card p-3 flex items-start gap-2 text-[10px] text-slate-600">
        <AlertTriangle size={13} className="shrink-0 mt-0.5 text-slate-500" />
        Detection is genuine — the same YOLOv8/ByteTrack/plate-OCR/ArcFace pipeline used for the
        30-camera Sentinel Grid, run here against the camera(s) you selected. No result is
        hardcoded; a non-matching face or plate will correctly produce no alert.
      </div>
    </div>
  );
}
