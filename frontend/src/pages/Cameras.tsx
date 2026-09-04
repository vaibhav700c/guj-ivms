import { useEffect, useState } from "react";
import {
  Search, Video, CircleDot, Copy, Check, Wifi, ArrowUpDown, X, Activity, Clock, Cpu,
  Plus, Upload, FileText, Trash2, AlertTriangle,
} from "lucide-react";
import { api, formatDateTime } from "../lib/api";

interface Camera {
  id: number; external_id: string | null; name: string;
  city: string | null; district: string | null; camera_type: string | null;
  analytics_tier: string; status: string; health_score: number | null;
  resolution: string | null; stream_url: string | null;
  rtsp_url: string | null; whep_url: string | null;
  stream_protocol: string | null; vms_vendor: string | null;
  latitude: number; longitude: number; address: string | null;
  has_ir: boolean; has_ptz: boolean;
}

interface HealthLog {
  time: string; status: string; fps_actual: number | null;
  latency_ms: number | null; packet_loss: number | null; error_message: string | null;
}

interface AnprEvent {
  id: number; plate_text: string; vehicle_type: string | null;
  confidence: number; timestamp: string; direction: string | null;
}

interface Department {
  id: number; name: string; code: string; description: string | null;
}

const STATUS_BADGE: Record<string, string> = {
  online: "badge-online", offline: "badge-offline",
  maintenance: "badge-maintenance", unknown: "bg-slate-500/10 text-slate-400 badge",
};
const TIER_BADGE: Record<string, string> = {
  A: "bg-orange-500/15 text-orange-400 border border-orange-500/20 badge",
  B: "bg-cyan-500/15 text-cyan-400 border border-cyan-500/20 badge",
  C: "bg-slate-500/15 text-slate-400 border border-slate-500/20 badge",
};
const TIER_DESC: Record<string, string> = {
  A: "ANPR + Face + Detection (5–10 FPS)",
  B: "Detection + Tracking (2–5 FPS)",
  C: "Presence / Health (1 FPS)",
};
const STATUS_ROW: Record<string, string> = {
  offline: "bg-red-500/3", maintenance: "bg-amber-500/3",
};

// Approximate bounding box for Gujarat — used only to warn, never to block.
const GUJARAT_BOUNDS = { latMin: 20, latMax: 24.7, lngMin: 68, lngMax: 74.5 };

const CAMERA_CSV_COLUMNS = ["name", "latitude", "longitude", "city", "district", "address", "camera_type", "analytics_tier"];

const SAMPLE_CAMERA_CSV = `name,latitude,longitude,city,district,address,camera_type,analytics_tier
Ring Road Junction,21.1702,72.8311,Surat,Surat,Ring Rd,anpr,A
Kankaria Lake Gate 2,23.0060,72.6015,Ahmedabad,Ahmedabad,Kankaria Rd,ptz,B`;

/** Turns a thrown api() Error (or anything else) into a readable message, unwrapping FastAPI's JSON error bodies. */
function describeApiError(err: unknown): string {
  if (!(err instanceof Error)) return String(err);
  const m = err.message.match(/^API (\d+): ([\s\S]*)$/);
  if (!m) return err.message;
  const [, status, rawBody] = m;
  let body = rawBody;
  try {
    const parsed = JSON.parse(rawBody);
    if (typeof parsed.detail === "string") {
      body = parsed.detail;
    } else if (Array.isArray(parsed.detail)) {
      body = parsed.detail
        .map((d: { loc?: string[]; msg?: string }) => (d.msg ? `${(d.loc ?? []).join(".")}: ${d.msg}` : JSON.stringify(d)))
        .join("; ");
    } else {
      body = JSON.stringify(parsed);
    }
  } catch {
    // not JSON — keep the raw text
  }
  return `Server error ${status}: ${body || "no details returned"}`;
}

/** Minimal CSV parser (no quoted-comma support) — sufficient for the flat camera import shape. */
function parseCsv(text: string): Record<string, string>[] {
  const lines = text.trim().split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((h) => h.trim());
  return lines.slice(1).map((line) => {
    const cells = line.split(",").map((c) => c.trim());
    const row: Record<string, string> = {};
    headers.forEach((h, i) => { row[h] = cells[i] ?? ""; });
    return row;
  });
}

function csvRowToCamera(row: Record<string, string>): Record<string, unknown> {
  const cam: Record<string, unknown> = { name: row.name ?? "" };
  if (row.latitude) cam.latitude = parseFloat(row.latitude);
  if (row.longitude) cam.longitude = parseFloat(row.longitude);
  if (row.city) cam.city = row.city;
  if (row.district) cam.district = row.district;
  if (row.address) cam.address = row.address;
  if (row.camera_type) cam.camera_type = row.camera_type;
  if (row.analytics_tier) cam.analytics_tier = row.analytics_tier.toUpperCase();
  return cam;
}

function isValidCameraPayload(c: Record<string, unknown>): boolean {
  return typeof c.name === "string" && c.name.trim().length > 0
    && typeof c.latitude === "number" && !Number.isNaN(c.latitude)
    && typeof c.longitude === "number" && !Number.isNaN(c.longitude);
}

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
  };
  return (
    <button onClick={copy} className="btn-icon w-6 h-6" title="Copy URL">
      {copied ? <Check size={10} className="text-emerald-400" /> : <Copy size={10} />}
    </button>
  );
}

type SortKey = "name" | "city" | "status" | "analytics_tier" | "health_score";

function CameraDrawer({
  camera, onClose, onDelete, deleting,
}: {
  camera: Camera; onClose: () => void; onDelete: () => void; deleting: boolean;
}) {
  const [healthLog, setHealthLog] = useState<HealthLog[]>([]);
  const [anprEvents, setAnprEvents] = useState<AnprEvent[]>([]);
  const [loadingHealth, setLoadingHealth] = useState(true);

  useEffect(() => {
    setLoadingHealth(true);
    Promise.all([
      api<{ items: HealthLog[] }>(`/cameras/${camera.id}/health-log?limit=20`)
        .then((r) => setHealthLog(r.items)).catch(() => undefined),
      api<{ items: AnprEvent[] }>(`/analytics/anpr?camera_id=${camera.id}&hours=24&limit=10`)
        .then((r) => setAnprEvents(r.items)).catch(() => undefined),
    ]).finally(() => setLoadingHealth(false));
  }, [camera.id]);

  const lastHealth = healthLog[0];
  const uptime = healthLog.length
    ? Math.round((healthLog.filter((h) => h.status === "online").length / healthLog.length) * 100)
    : null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="w-full max-w-sm h-full bg-control-900 border-l border-control-800 flex flex-col overflow-hidden animate-slide-in-up shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 border-b border-control-800 flex items-start justify-between">
          <div>
            <div className="text-sm font-bold text-white">{camera.name}</div>
            <div className="text-[10px] font-mono text-slate-500 mt-0.5">{camera.external_id} · {camera.vms_vendor}</div>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onDelete} disabled={deleting}
              className="btn-icon hover:!bg-red-500/20 hover:!text-red-400 disabled:opacity-50"
              title="Delete camera">
              <Trash2 size={13} />
            </button>
            <button onClick={onClose} className="btn-icon"><X size={14} /></button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">

          {/* Status row */}
          <div className="flex flex-wrap gap-2">
            <span className={`${STATUS_BADGE[camera.status] ?? STATUS_BADGE.unknown} capitalize flex items-center gap-1`}>
              <CircleDot size={9} /> {camera.status}
            </span>
            <span className={TIER_BADGE[camera.analytics_tier] ?? TIER_BADGE.C} title={TIER_DESC[camera.analytics_tier]}>
              Tier {camera.analytics_tier}
            </span>
            {camera.has_ir && <span className="badge bg-violet-500/15 text-violet-400 border border-violet-500/20">IR</span>}
            {camera.has_ptz && <span className="badge bg-cyan-500/15 text-cyan-400 border border-cyan-500/20">PTZ</span>}
          </div>

          {/* Info grid */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            {[
              { label: "City", value: camera.city },
              { label: "District", value: camera.district },
              { label: "Type", value: camera.camera_type },
              { label: "Resolution", value: camera.resolution },
              { label: "Health Score", value: camera.health_score != null ? `${Math.round(camera.health_score * 100)}%` : "—" },
              { label: "Protocol", value: camera.stream_protocol },
            ].map(({ label, value }) => (
              <div key={label} className="bg-control-850 rounded-lg p-2 border border-control-800/50">
                <div className="text-[9px] text-slate-600 uppercase tracking-wider mb-0.5">{label}</div>
                <div className="text-slate-300 font-medium">{value ?? "—"}</div>
              </div>
            ))}
          </div>

          {/* Stream URLs */}
          {(camera.stream_url || camera.rtsp_url) && (
            <div className="space-y-1.5">
              <div className="text-[10px] text-slate-600 uppercase tracking-wider font-semibold">Stream URLs</div>
              {camera.stream_url && (
                <div className="flex items-center gap-2 bg-control-850 rounded-lg px-3 py-2 border border-control-800/50">
                  <Wifi size={10} className="text-emerald-400 shrink-0" />
                  <span className="font-mono text-[10px] text-emerald-400 truncate flex-1">{camera.stream_url}</span>
                  <CopyBtn text={camera.stream_url} />
                </div>
              )}
              {camera.rtsp_url && (
                <div className="flex items-center gap-2 bg-control-850 rounded-lg px-3 py-2 border border-control-800/50">
                  <Video size={10} className="text-cyan-400 shrink-0" />
                  <span className="font-mono text-[10px] text-cyan-400 truncate flex-1">{camera.rtsp_url}</span>
                  <CopyBtn text={camera.rtsp_url} />
                </div>
              )}
            </div>
          )}

          {/* Health log */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[10px] text-slate-600 uppercase tracking-wider font-semibold">
              <Activity size={10} /> Health Log (last 20 samples)
            </div>
            {loadingHealth ? (
              <div className="text-xs text-slate-600 py-2">Loading…</div>
            ) : healthLog.length === 0 ? (
              <div className="text-xs text-slate-600 py-2">No health data recorded yet.</div>
            ) : (
              <>
                {uptime !== null && (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-slate-500">Uptime:</span>
                    <div className="flex-1 h-1.5 bg-control-800 rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all"
                        style={{ width: `${uptime}%`, background: uptime > 80 ? "#10b981" : uptime > 50 ? "#f59e0b" : "#ef4444" }} />
                    </div>
                    <span className="font-mono text-slate-400">{uptime}%</span>
                  </div>
                )}
                {lastHealth && (
                  <div className="grid grid-cols-3 gap-1.5 text-center">
                    {[
                      { icon: Cpu, label: "FPS", value: lastHealth.fps_actual?.toFixed(1) ?? "—", color: "text-cyan-400" },
                      { icon: Clock, label: "Latency", value: lastHealth.latency_ms ? `${lastHealth.latency_ms}ms` : "—", color: "text-orange-400" },
                      { icon: Activity, label: "Loss", value: lastHealth.packet_loss ? `${(lastHealth.packet_loss * 100).toFixed(1)}%` : "0%", color: "text-violet-400" },
                    ].map(({ icon: Icon, label, value, color }) => (
                      <div key={label} className="bg-control-850 rounded-lg p-2 border border-control-800/50">
                        <Icon size={12} className={`mx-auto mb-1 ${color}`} />
                        <div className={`text-sm font-bold ${color}`}>{value}</div>
                        <div className="text-[9px] text-slate-600">{label}</div>
                      </div>
                    ))}
                  </div>
                )}
                <div className="space-y-0.5 max-h-32 overflow-y-auto">
                  {healthLog.map((h, i) => (
                    <div key={i} className="flex items-center gap-2 text-[10px] font-mono text-slate-500">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${h.status === "online" ? "bg-emerald-500" : "bg-red-500"}`} />
                      <span className="text-slate-600">{formatDateTime(h.time)}</span>
                      <span className="text-slate-500">{h.fps_actual != null ? `${h.fps_actual.toFixed(1)} fps` : ""}</span>
                      <span className="text-slate-700">{h.latency_ms != null ? `${h.latency_ms}ms` : ""}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Recent ANPR events */}
          {camera.analytics_tier === "A" || camera.analytics_tier === "B" ? (
            <div className="space-y-2">
              <div className="text-[10px] text-slate-600 uppercase tracking-wider font-semibold">Recent ANPR (24h)</div>
              {anprEvents.length === 0 ? (
                <div className="text-xs text-slate-600">No ANPR events in last 24h.</div>
              ) : (
                <div className="space-y-0.5 max-h-32 overflow-y-auto">
                  {anprEvents.map((e) => (
                    <div key={e.id} className="flex items-center gap-2 bg-control-850 rounded-lg px-2.5 py-1.5 border border-control-800/50">
                      <span className="font-mono text-xs text-orange-400 font-semibold">{e.plate_text}</span>
                      <span className="text-[10px] text-slate-600 ml-auto">{formatDateTime(e.timestamp)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}

        </div>
      </div>
    </div>
  );
}

interface CameraFormState {
  name: string; latitude: string; longitude: string; city: string; district: string;
  address: string; camera_type: string; stream_url: string; stream_protocol: string;
  resolution: string; fps: string; analytics_tier: string; department_id: string;
}

const EMPTY_CAMERA_FORM: CameraFormState = {
  name: "", latitude: "", longitude: "", city: "", district: "", address: "",
  camera_type: "", stream_url: "", stream_protocol: "hls", resolution: "",
  fps: "", analytics_tier: "C", department_id: "",
};

const FIELD_LABEL = "text-[10px] text-slate-500 uppercase tracking-wider";

function AddCameraDrawer({
  departments, onClose, onCreated,
}: {
  departments: Department[]; onClose: () => void; onCreated: () => void;
}) {
  const [form, setForm] = useState<CameraFormState>(EMPTY_CAMERA_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (patch: Partial<CameraFormState>) => setForm((f) => ({ ...f, ...patch }));

  const lat = parseFloat(form.latitude);
  const lng = parseFloat(form.longitude);
  const nameValid = form.name.trim().length > 0;
  const latValid = form.latitude.trim() !== "" && !Number.isNaN(lat) && lat >= -90 && lat <= 90;
  const lngValid = form.longitude.trim() !== "" && !Number.isNaN(lng) && lng >= -180 && lng <= 180;
  const outsideGujarat = latValid && lngValid
    && (lat < GUJARAT_BOUNDS.latMin || lat > GUJARAT_BOUNDS.latMax || lng < GUJARAT_BOUNDS.lngMin || lng > GUJARAT_BOUNDS.lngMax);
  const canSubmit = nameValid && latValid && lngValid && !submitting;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        latitude: lat,
        longitude: lng,
        city: form.city.trim() || null,
        district: form.district.trim() || null,
        address: form.address.trim() || null,
        camera_type: form.camera_type.trim() || null,
        stream_url: form.stream_url.trim() || null,
        stream_protocol: form.stream_protocol || null,
        resolution: form.resolution.trim() || null,
        fps: form.fps.trim() ? Number(form.fps) : null,
        analytics_tier: form.analytics_tier,
        department_id: form.department_id ? Number(form.department_id) : null,
      };
      await api("/cameras", { method: "POST", body: JSON.stringify(body) });
      onCreated();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={submitting ? undefined : onClose}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm h-full bg-control-900 border-l border-control-800 flex flex-col overflow-hidden animate-slide-in-up shadow-2xl"
      >
        <div className="p-4 border-b border-control-800 flex items-center justify-between">
          <div className="text-sm font-bold text-white">Add Camera</div>
          <button type="button" onClick={onClose} disabled={submitting} className="btn-icon"><X size={14} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {error && (
            <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              <AlertTriangle size={13} className="shrink-0 mt-0.5" /> <span className="whitespace-pre-wrap">{error}</span>
            </div>
          )}

          <div>
            <label className={FIELD_LABEL}>Name *</label>
            <input className="input mt-1" value={form.name} onChange={(e) => set({ name: e.target.value })}
              placeholder="e.g. Ring Road Junction" />
            {!nameValid && form.name.length > 0 && <div className="text-[10px] text-red-400 mt-1">Name is required.</div>}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={FIELD_LABEL}>Latitude *</label>
              <input className="input mt-1" value={form.latitude} onChange={(e) => set({ latitude: e.target.value })}
                placeholder="21.1702" inputMode="decimal" />
            </div>
            <div>
              <label className={FIELD_LABEL}>Longitude *</label>
              <input className="input mt-1" value={form.longitude} onChange={(e) => set({ longitude: e.target.value })}
                placeholder="72.8311" inputMode="decimal" />
            </div>
          </div>
          {form.latitude.trim() !== "" && !latValid && (
            <div className="text-[10px] text-red-400">Latitude must be a number between -90 and 90.</div>
          )}
          {form.longitude.trim() !== "" && !lngValid && (
            <div className="text-[10px] text-red-400">Longitude must be a number between -180 and 180.</div>
          )}
          {outsideGujarat && (
            <div className="flex items-start gap-2 text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-2.5 py-1.5">
              <AlertTriangle size={11} className="shrink-0 mt-0.5" />
              Outside Gujarat&apos;s approximate bounds (lat 20–24.7, lng 68–74.5). Double-check before saving — this will not block submission.
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={FIELD_LABEL}>City</label>
              <input className="input mt-1" value={form.city} onChange={(e) => set({ city: e.target.value })} />
            </div>
            <div>
              <label className={FIELD_LABEL}>District</label>
              <input className="input mt-1" value={form.district} onChange={(e) => set({ district: e.target.value })} />
            </div>
          </div>

          <div>
            <label className={FIELD_LABEL}>Address</label>
            <input className="input mt-1" value={form.address} onChange={(e) => set({ address: e.target.value })} />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={FIELD_LABEL}>Camera Type</label>
              <input className="input mt-1" list="camera-type-options" value={form.camera_type}
                onChange={(e) => set({ camera_type: e.target.value })} placeholder="anpr" />
              <datalist id="camera-type-options">
                <option value="anpr" /><option value="ptz" /><option value="dome" /><option value="bullet" />
                <option value="fixed" /><option value="thermal" /><option value="ir" /><option value="analog" />
              </datalist>
            </div>
            <div>
              <label className={FIELD_LABEL}>Stream Protocol</label>
              <select className="input mt-1" value={form.stream_protocol} onChange={(e) => set({ stream_protocol: e.target.value })}>
                <option value="hls">HLS</option>
                <option value="rtsp">RTSP</option>
                <option value="rtmp">RTMP</option>
                <option value="onvif">ONVIF</option>
              </select>
            </div>
          </div>

          <div>
            <label className={FIELD_LABEL}>Stream URL</label>
            <input className="input mt-1 font-mono text-xs" value={form.stream_url}
              onChange={(e) => set({ stream_url: e.target.value })} placeholder="optional" />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={FIELD_LABEL}>Resolution</label>
              <input className="input mt-1" list="resolution-options" value={form.resolution}
                onChange={(e) => set({ resolution: e.target.value })} placeholder="1080p" />
              <datalist id="resolution-options">
                <option value="720p" /><option value="1080p" /><option value="4mp" /><option value="4k" />
              </datalist>
            </div>
            <div>
              <label className={FIELD_LABEL}>FPS</label>
              <input className="input mt-1" value={form.fps} onChange={(e) => set({ fps: e.target.value })}
                inputMode="numeric" placeholder="25" />
            </div>
          </div>

          <div>
            <label className={FIELD_LABEL}>Department</label>
            <select className="input mt-1" value={form.department_id} onChange={(e) => set({ department_id: e.target.value })}>
              <option value="">— Unassigned —</option>
              {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>

          <div>
            <label className={FIELD_LABEL}>Analytics Tier</label>
            <select className="input mt-1" value={form.analytics_tier} onChange={(e) => set({ analytics_tier: e.target.value })}>
              <option value="A">Tier A</option>
              <option value="B">Tier B</option>
              <option value="C">Tier C</option>
            </select>
            <div className="text-[10px] text-slate-500 mt-1">{TIER_DESC[form.analytics_tier]}</div>
          </div>
        </div>

        <div className="p-4 border-t border-control-800 flex gap-2">
          <button type="button" className="btn-ghost flex-1 justify-center" onClick={onClose} disabled={submitting}>Cancel</button>
          <button type="submit" className="btn-primary flex-1 justify-center" disabled={!canSubmit}>
            {submitting ? "Saving… (cold start can take ~20s)" : "Add Camera"}
          </button>
        </div>
      </form>
    </div>
  );
}

function BulkImportPanel({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => { setText((ev.target?.result as string) ?? ""); setResult(null); setError(null); };
    reader.readAsText(file);
    e.target.value = "";
  };

  const submit = async () => {
    setError(null);
    setResult(null);
    const trimmed = text.trim();
    if (!trimmed) { setError("Paste a JSON array or CSV data first."); return; }

    let payload: Record<string, unknown>[];
    try {
      if (trimmed.startsWith("[")) {
        const parsed = JSON.parse(trimmed);
        if (!Array.isArray(parsed)) throw new Error("JSON input must be an array of camera objects.");
        payload = parsed;
      } else {
        const rows = parseCsv(trimmed);
        if (rows.length === 0) throw new Error("No data rows found — check the CSV header row.");
        payload = rows.map(csvRowToCamera);
      }
    } catch (err) {
      setError(`Could not parse input: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }

    const badRow = payload.findIndex((c) => !isValidCameraPayload(c));
    if (badRow !== -1) {
      setError(`Row ${badRow + 1} is missing a valid name, latitude, or longitude.`);
      return;
    }

    setLoading(true);
    try {
      const res = await api<{ imported: number; items: unknown[] }>("/cameras/bulk", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setResult(`Imported ${res.imported} of ${payload.length} camera${payload.length === 1 ? "" : "s"}.`);
      setText("");
      onImported();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <FileText size={14} className="text-orange-400" /> Bulk Import Cameras
        </div>
        <button onClick={onClose} className="btn-icon" disabled={loading}><X size={13} /></button>
      </div>
      <p className="text-xs text-slate-500">
        Paste a JSON array of camera objects, or CSV with columns{" "}
        <code className="font-mono text-orange-400">{CAMERA_CSV_COLUMNS.join(",")}</code>. Or upload a file.
      </p>
      <div className="flex items-center gap-2">
        <label className="btn-ghost text-xs cursor-pointer">
          <Upload size={12} /> Choose File (.csv / .json)
          <input type="file" accept=".csv,.json,.txt" className="hidden" onChange={handleFile} disabled={loading} />
        </label>
        <button className="btn-ghost text-xs" onClick={() => { setText(SAMPLE_CAMERA_CSV); setResult(null); setError(null); }} disabled={loading}>
          Load sample CSV
        </button>
      </div>
      <textarea
        className="input w-full font-mono text-xs"
        rows={8}
        placeholder={"name,latitude,longitude,city,district,address,camera_type,analytics_tier\nRing Road Junction,21.1702,72.8311,Surat,Surat,Ring Rd,anpr,A"}
        value={text}
        onChange={(e) => { setText(e.target.value); setResult(null); setError(null); }}
        disabled={loading}
      />
      {error && (
        <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertTriangle size={13} className="shrink-0 mt-0.5" /> <span className="whitespace-pre-wrap">{error}</span>
        </div>
      )}
      {result && (
        <div className="text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">{result}</div>
      )}
      <button className="btn-primary" disabled={loading || !text.trim()} onClick={submit}>
        {loading ? "Importing… (cold start can take ~20s)" : "Import Now"}
      </button>
    </div>
  );
}

export default function Cameras() {
  const [items, setItems] = useState<Camera[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [status, setStatus] = useState("");
  const [cities, setCities] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortAsc, setSortAsc] = useState(true);
  const [drawerCam, setDrawerCam] = useState<Camera | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [showAddForm, setShowAddForm] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    api<{ by_city: Record<string, number> }>("/cameras/stats")
      .then((s) => setCities(Object.keys(s.by_city).sort()))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    api<Department[]>("/cameras/departments/list").then(setDepartments).catch(() => undefined);
  }, []);

  const load = () => {
    const params = new URLSearchParams({ limit: "500" });
    if (q) params.set("q", q);
    if (city) params.set("city", city);
    if (status) params.set("status", status);
    return api<{ total: number; items: Camera[] }>(`/cameras?${params}`)
      .then((r) => { setItems(r.items); setTotal(r.total); });
  };

  useEffect(() => { load().catch(() => undefined); }, [q, city, status]);

  const deleteCamera = async (cam: Camera) => {
    if (!window.confirm(`Delete camera "${cam.name}"? This cannot be undone.`)) return;
    setDeleteError(null);
    setDeletingId(cam.id);
    try {
      await api(`/cameras/${cam.id}`, { method: "DELETE" });
      if (drawerCam?.id === cam.id) setDrawerCam(null);
      await load();
    } catch (err) {
      setDeleteError(`Failed to delete "${cam.name}" — ${describeApiError(err)}`);
    } finally {
      setDeletingId(null);
    }
  };

  const sorted = [...items].sort((a, b) => {
    const aVal = a[sortKey] ?? ""; const bVal = b[sortKey] ?? "";
    if (aVal < bVal) return sortAsc ? -1 : 1;
    if (aVal > bVal) return sortAsc ? 1 : -1;
    return 0;
  });

  const sort = (key: SortKey) => {
    if (sortKey === key) setSortAsc((v) => !v);
    else { setSortKey(key); setSortAsc(true); }
  };

  const SortTh = ({ col, label }: { col: SortKey; label: string }) => (
    <th className="table-head cursor-pointer hover:text-slate-300 transition-colors select-none"
      onClick={() => sort(col)}>
      <div className="flex items-center gap-1">
        {label}
        <ArrowUpDown size={10} className={sortKey === col ? "text-orange-400" : "text-slate-700"} />
      </div>
    </th>
  );

  const online = items.filter((c) => c.status === "online").length;
  const offline = items.filter((c) => c.status === "offline").length;

  return (
    <div className="space-y-5 max-w-[1500px] animate-fade-in">

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Camera Registry</h1>
          <p className="page-subtitle">
            Sentinel Grid · {total} cameras · {online} online · {offline} offline · Click any row for details
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex gap-2">
            <button className="btn-ghost text-xs" onClick={() => { setShowBulk((v) => !v); setShowAddForm(false); }}>
              <Upload size={13} /> Bulk Import
            </button>
            <button className="btn-primary text-xs" onClick={() => setShowAddForm(true)}>
              <Plus size={14} /> Add Camera
            </button>
          </div>
          <div className="flex gap-2">
            {[
              { label: `${online} Online`, cls: "text-emerald-400 bg-emerald-500/10 border border-emerald-500/20" },
              { label: `${offline} Offline`, cls: "text-red-400 bg-red-500/10 border border-red-500/20" },
              { label: `${items.filter((c) => c.status === "maintenance").length} Maintenance`, cls: "text-amber-400 bg-amber-500/10 border border-amber-500/20" },
            ].map((s) => (
              <div key={s.label} className={`px-3 py-1.5 rounded-xl text-xs font-semibold ${s.cls}`}>{s.label}</div>
            ))}
          </div>
        </div>
      </div>

      {/* Delete error banner */}
      {deleteError && (
        <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-3.5 py-2.5">
          <AlertTriangle size={13} className="shrink-0 mt-0.5" />
          <span className="flex-1">{deleteError}</span>
          <button onClick={() => setDeleteError(null)} className="text-slate-500 hover:text-slate-300"><X size={12} /></button>
        </div>
      )}

      {/* Bulk import panel */}
      {showBulk && (
        <BulkImportPanel
          onClose={() => setShowBulk(false)}
          onImported={() => load().catch(() => undefined)}
        />
      )}

      {/* Filters */}
      <div className="card p-4 flex flex-wrap gap-3 items-center">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search name, city, road…"
            value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className="input w-40" value={city} onChange={(e) => setCity(e.target.value)}>
          <option value="">All cities</option>
          {cities.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="input w-36" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="maintenance">Maintenance</option>
        </select>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px]">
            <thead>
              <tr className="border-b border-control-800 bg-control-850">
                <SortTh col="name" label="Camera" />
                <SortTh col="city" label="Location" />
                <th className="table-head">Type</th>
                <SortTh col="analytics_tier" label="Tier" />
                <th className="table-head">Stream URLs</th>
                <SortTh col="health_score" label="Health" />
                <SortTh col="status" label="Status" />
                <th className="table-head"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-control-800/40">
              {sorted.map((c) => (
                <tr key={c.id}
                  className={`table-row cursor-pointer ${STATUS_ROW[c.status] ?? ""}`}
                  onClick={() => setDrawerCam(c)}>
                  <td className="table-cell">
                    <div className="flex items-center gap-2">
                      <div className={`w-1.5 h-6 rounded-full shrink-0 ${c.status === "online" ? "bg-emerald-500" : c.status === "offline" ? "bg-red-500" : "bg-amber-500"}`} />
                      <div>
                        <div className="font-semibold text-slate-200 text-sm">{c.name}</div>
                        <div className="text-[10px] font-mono text-slate-600">{c.external_id}</div>
                      </div>
                    </div>
                  </td>
                  <td className="table-cell">
                    <div className="text-sm text-slate-300">{c.city}</div>
                    <div className="text-[10px] text-slate-600">{c.district}</div>
                  </td>
                  <td className="table-cell">
                    <span className="text-xs text-slate-400 capitalize">{c.camera_type ?? "—"}</span>
                  </td>
                  <td className="table-cell">
                    <span className={TIER_BADGE[c.analytics_tier] ?? TIER_BADGE.C} title={TIER_DESC[c.analytics_tier]}>
                      Tier {c.analytics_tier}
                    </span>
                  </td>
                  <td className="table-cell" onClick={(e) => e.stopPropagation()}>
                    <div className="flex flex-col gap-1">
                      {c.stream_url && (
                        <div className="flex items-center gap-1">
                          <Wifi size={9} className="text-emerald-400" />
                          <span className="text-[10px] font-mono text-emerald-400">HLS</span>
                          <CopyBtn text={c.stream_url} />
                        </div>
                      )}
                      {c.rtsp_url && (
                        <div className="flex items-center gap-1">
                          <Video size={9} className="text-cyan-400" />
                          <span className="text-[10px] font-mono text-cyan-400">RTSP (TCP)</span>
                          <CopyBtn text={c.rtsp_url} />
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="table-cell">
                    <div className="flex items-center gap-2">
                      <div className="w-14 h-1.5 rounded-full bg-control-700 overflow-hidden">
                        <div className={`h-full rounded-full ${(c.health_score ?? 0) > 0.8 ? "bg-emerald-500" : (c.health_score ?? 0) > 0.5 ? "bg-amber-500" : "bg-red-500"}`}
                          style={{ width: `${Math.round((c.health_score ?? 0) * 100)}%` }} />
                      </div>
                      <span className="font-mono text-xs text-slate-500">
                        {c.health_score != null ? `${Math.round(c.health_score * 100)}%` : "—"}
                      </span>
                    </div>
                  </td>
                  <td className="table-cell">
                    <span className={`${STATUS_BADGE[c.status] ?? STATUS_BADGE.unknown} capitalize flex items-center gap-1`}>
                      <CircleDot size={9} /> {c.status}
                    </span>
                  </td>
                  <td className="table-cell" onClick={(e) => e.stopPropagation()}>
                    <button className="btn-icon hover:!bg-red-500/20 hover:!text-red-400 disabled:opacity-50"
                      title="Delete camera" disabled={deletingId === c.id} onClick={() => deleteCamera(c)}>
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={8} className="table-cell text-center text-slate-600 py-12">
                    No cameras match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Camera detail drawer */}
      {drawerCam && (
        <CameraDrawer
          camera={drawerCam}
          onClose={() => setDrawerCam(null)}
          onDelete={() => deleteCamera(drawerCam)}
          deleting={deletingId === drawerCam.id}
        />
      )}

      {/* Add camera drawer */}
      {showAddForm && (
        <AddCameraDrawer
          departments={departments}
          onClose={() => setShowAddForm(false)}
          onCreated={() => { setShowAddForm(false); load().catch(() => undefined); }}
        />
      )}
    </div>
  );
}
