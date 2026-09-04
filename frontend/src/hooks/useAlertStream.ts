import { useEffect } from "react";
import { create } from "zustand";
import { wsUrl } from "../lib/api";

export interface TickerAlert {
  severity: string;
  message: string;
  timestamp: string;
}

/** Loosely typed — this is the raw `payload` of a `type: "alert"` WS message. */
export interface AlertStreamPayload {
  id?: number;
  alert_type?: string;
  severity: string;
  camera_name?: string | null;
  detected_identifier?: string | null;
  match_confidence?: number | null;
  message?: string | null;
  status?: string;
  timestamp: string;
  [key: string]: unknown;
}

interface AlertStreamEvent {
  payload: AlertStreamPayload;
  /** Monotonically increasing — lets consumers depend on "a new message arrived" via useEffect. */
  seq: number;
}

const SOUND_KEY = "ivms_sound_enabled";
const BASE_RETRY_MS = 3000;
const MAX_RETRY_MS = 20000;

interface AlertStreamState {
  connected: boolean;
  unread: number;
  ticker: TickerAlert[];
  soundOn: boolean;
  lastEvent: AlertStreamEvent | null;
  clearUnread: () => void;
  toggleSound: () => void;
}

export const useAlertStreamStore = create<AlertStreamState>((set) => ({
  connected: false,
  unread: 0,
  ticker: [],
  soundOn: localStorage.getItem(SOUND_KEY) !== "false",
  lastEvent: null,
  clearUnread: () => set({ unread: 0 }),
  toggleSound: () =>
    set((s) => {
      const next = !s.soundOn;
      localStorage.setItem(SOUND_KEY, String(next));
      return { soundOn: next };
    }),
}));

// ── Module-level singleton connection — shared by every consumer of useAlertStream ──
let ws: WebSocket | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let retryAttempt = 0;
let seqCounter = 0;
let started = false;

function playBeep() {
  if (!useAlertStreamStore.getState().soundOn) return;
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
    osc.start();
    osc.stop(ctx.currentTime + 0.4);
  } catch {
    /* no audio context available */
  }
}

function scheduleReconnect() {
  if (!started) return;
  const delay = Math.min(BASE_RETRY_MS * 1.6 ** retryAttempt, MAX_RETRY_MS);
  retryAttempt += 1;
  clearTimeout(retryTimer ?? undefined);
  retryTimer = setTimeout(connect, delay);
}

function connect() {
  if (!started || ws) return;
  try {
    ws = new WebSocket(wsUrl());
  } catch {
    ws = null;
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    retryAttempt = 0;
    useAlertStreamStore.setState({ connected: true });
  };

  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data?.type !== "alert") return;
      const payload: AlertStreamPayload = data.payload ?? {
        severity: data.severity ?? "medium",
        message: data.message ?? "Alert",
        timestamp: data.timestamp ?? new Date().toISOString(),
      };
      seqCounter += 1;
      useAlertStreamStore.setState((s) => ({
        unread: s.unread + 1,
        ticker: [
          { severity: payload.severity ?? "medium", message: payload.message ?? "Alert", timestamp: payload.timestamp ?? new Date().toISOString() },
          ...s.ticker,
        ].slice(0, 20),
        lastEvent: { payload, seq: seqCounter },
      }));
      if (payload.severity === "critical" || payload.severity === "high") playBeep();
    } catch {
      /* ignore malformed message */
    }
  };

  ws.onclose = () => {
    ws = null;
    useAlertStreamStore.setState({ connected: false });
    scheduleReconnect();
  };

  ws.onerror = () => {
    ws?.close();
  };
}

function teardown() {
  started = false;
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  retryAttempt = 0;
  if (ws) {
    const socket = ws;
    ws = null;
    socket.onopen = null;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
    socket.close();
  }
  useAlertStreamStore.setState({ connected: false });
}

/**
 * Shared `/ws/alerts` connection. Exactly one physical WebSocket exists for the
 * whole app no matter how many components call this hook.
 *
 * Pass `manage: true` from the ONE place that should own the connection's
 * lifecycle (Layout, mounted for the whole authenticated session). Every other
 * consumer (e.g. the Alerts page) should call it with no arguments — it just
 * reads the shared state and reacts to `lastEvent`.
 */
export function useAlertStream(manage = false) {
  useEffect(() => {
    if (!manage) return;
    started = true;
    connect();
    return () => teardown();
  }, [manage]);

  return useAlertStreamStore();
}
