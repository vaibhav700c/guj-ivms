import { create } from "zustand";

/**
 * Global "Real detections only" preference — see backend `source` column on
 * ANPREvent/DetectionEvent/Alert/CameraHealthLog (app/models.py) and
 * CLAUDE.md "Two event sources". When ON (the default), every list/search
 * page requests `?source=edge_worker` so fabricated simulator output never
 * appears indistinguishable from a genuine detection. Persisted across
 * reloads via localStorage; the honest default (real-only) always wins on
 * first visit.
 */
const STORAGE_KEY = "ivms_real_only";

function readInitial(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === null) return true; // default: real detections only
    return raw === "true";
  } catch {
    return true;
  }
}

interface SettingsState {
  realOnly: boolean;
  setRealOnly: (value: boolean) => void;
  toggleRealOnly: () => void;
}

export const useSettings = create<SettingsState>((set, get) => ({
  realOnly: readInitial(),
  setRealOnly: (value) => {
    try {
      localStorage.setItem(STORAGE_KEY, String(value));
    } catch {
      /* localStorage unavailable — in-memory only for this session */
    }
    set({ realOnly: value });
  },
  toggleRealOnly: () => get().setRealOnly(!get().realOnly),
}));

/** Convenience: the `source` query param value implied by the current toggle,
 * or `null` when it's off (no filtering — show everything). */
export function realOnlySourceParam(): "edge_worker" | null {
  return useSettings.getState().realOnly ? "edge_worker" : null;
}
