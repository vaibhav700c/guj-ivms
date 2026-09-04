import { create } from "zustand";
import { useAuth } from "../store/auth";

const BASE = import.meta.env.VITE_API_URL ?? "";

/** How long a request may sit in flight before we assume the free-tier
 *  backend is cold-starting and surface the "waking up" banner. Render's
 *  free tier can take ~20s to serve the first request after idling. */
const SLOW_REQUEST_MS = 4000;

/**
 * Thrown by api() for every non-2xx response or network failure.
 * `status === null` means the request never got an HTTP response at all
 * (fetch threw — DNS/CORS/connection failure, most often a sleeping
 * Render instance that hasn't started accepting connections yet).
 * `status` being a number means the backend is reachable but returned
 * an error (4xx/5xx) — a real application-level failure, not a "waking up" case.
 */
export class ApiError extends Error {
  status: number | null;
  body: string | null;
  constructor(message: string, status: number | null, body: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Turns an ApiError (or anything else) into a short, readable message for the UI. */
export function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === null) {
      return "Cannot reach the backend — it may be waking up from sleep (Render free tier can take ~20s) or your network is offline.";
    }
    let body = err.body ?? "";
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed.detail === "string") body = parsed.detail;
      else if (Array.isArray(parsed.detail)) {
        body = parsed.detail
          .map((d: { loc?: string[]; msg?: string }) => (d.msg ? `${(d.loc ?? []).join(".")}: ${d.msg}` : JSON.stringify(d)))
          .join("; ");
      } else body = JSON.stringify(parsed);
    } catch {
      // not JSON — keep the raw text
    }
    return `Server error ${err.status}${body ? `: ${body}` : ""}`;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}

interface BackendStatusState {
  /** true while we believe the backend is unreachable / cold-starting. */
  waking: boolean;
}

/** Tiny shared store so any part of the app can show a "backend waking up" indicator. */
export const useBackendStatus = create<BackendStatusState>(() => ({
  waking: false,
}));

function setWaking(waking: boolean) {
  if (useBackendStatus.getState().waking !== waking) useBackendStatus.setState({ waking });
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = useAuth.getState().token;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  // If the request is still pending after SLOW_REQUEST_MS, assume the
  // backend is cold-starting and let the whole app know.
  const slowTimer = setTimeout(() => setWaking(true), SLOW_REQUEST_MS);

  let res: Response;
  try {
    res = await fetch(`${BASE}/api/v1${path}`, { ...options, headers });
  } catch {
    clearTimeout(slowTimer);
    setWaking(true);
    throw new ApiError(
      "Cannot reach the backend — it may be waking up from sleep (Render free tier can take ~20s) or your network is offline.",
      null
    );
  }
  clearTimeout(slowTimer);
  // We got a real HTTP response, so the backend is up and reachable —
  // clear the "waking" banner even if this particular request errored.
  setWaking(false);

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(`API ${res.status}: ${detail}`, res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function wsUrl(): string {
  const env = import.meta.env.VITE_WS_URL as string | undefined;
  if (env) return `${env}/ws/alerts`;
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/alerts`;
}

export function snapshotUrl(cameraId: number | string | null | undefined): string | null {
  if (cameraId === null || cameraId === undefined || cameraId === "") return null;
  return `${BASE}/api/v1/feeds/${cameraId}/snapshot`;
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-IN", { hour12: false });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { hour12: false });
}
