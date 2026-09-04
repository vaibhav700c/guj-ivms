import { useEffect, useState } from "react";
import { Plus, Trash2, ListChecks, Upload, X, FileText } from "lucide-react";
import { api, describeApiError } from "../lib/api";
import InlineError from "../components/InlineError";

interface Entry {
  id: number;
  category: string;
  subject_type: string;
  identifier: string;
  description: string | null;
  severity: string;
  fir_number: string | null;
  police_station: string | null;
  active: boolean;
}

const SEV_STYLE: Record<string, string> = {
  critical: "bg-red-500/15 text-red-400",
  high: "bg-orange-500/15 text-orange-400",
  medium: "bg-amber-500/15 text-amber-400",
  low: "bg-slate-500/15 text-slate-400",
};

const CAT_LABEL: Record<string, string> = {
  stolen_vehicle: "Stolen Vehicle",
  blacklisted_vehicle: "Blacklisted Vehicle",
  wanted_person: "Wanted Person",
  missing_person: "Missing Person",
  custom: "Custom",
};

const SAMPLE_CSV = `category,subject_type,identifier,severity,description,fir_number
stolen_vehicle,vehicle,GJ 05 BX 9012,high,Stolen from Surat market,FIR/2024/SRT/042
wanted_person,person,Raju Desai,critical,Wanted for robbery Ahmedabad,FIR/2024/AHD/108
stolen_vehicle,vehicle,GJ 01 KL 3344,medium,Two-wheeler theft Vadodara,FIR/2024/VDR/019`;

export default function Watchlist() {
  const [items, setItems] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [bulkResult, setBulkResult] = useState<{ created: number; skipped: number } | null>(null);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [form, setForm] = useState({
    category: "stolen_vehicle",
    subject_type: "vehicle",
    identifier: "",
    description: "",
    severity: "high",
    fir_number: "",
  });

  const load = () => {
    setLoading(true);
    api<{ items: Entry[] }>("/watchlist")
      .then((r) => { setItems(r.items); setError(null); })
      .catch((err) => setError(describeApiError(err)))
      .finally(() => { setLoading(false); setLoadedOnce(true); });
  };
  useEffect(load, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionError(null);
    try {
      await api("/watchlist", {
        method: "POST",
        body: JSON.stringify({ ...form, description: form.description || null, fir_number: form.fir_number || null }),
      });
      setShowForm(false);
      setForm({ ...form, identifier: "", description: "", fir_number: "" });
      load();
    } catch (err) {
      setActionError(describeApiError(err));
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Remove this watchlist entry?")) return;
    setActionError(null);
    try {
      await api(`/watchlist/${id}`, { method: "DELETE" });
      load();
    } catch (err) {
      setActionError(describeApiError(err));
    }
  };

  const toggle = async (entry: Entry) => {
    setActionError(null);
    try {
      await api(`/watchlist/${entry.id}`, { method: "PATCH", body: JSON.stringify({ active: !entry.active }) });
      load();
    } catch (err) {
      setActionError(describeApiError(err));
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => setBulkText(ev.target?.result as string);
    reader.readAsText(file);
    e.target.value = "";
  };

  const submitBulk = async () => {
    if (!bulkText.trim()) return;
    setBulkLoading(true);
    setBulkResult(null);
    setBulkError(null);
    try {
      const isCSV = bulkText.trim().startsWith("category") || bulkText.includes(",");
      const result = await api<{ created: number; skipped: number }>("/watchlist/bulk-import", {
        method: "POST",
        headers: { "Content-Type": isCSV ? "text/csv" : "application/json" },
        body: bulkText,
      });
      setBulkResult(result);
      load();
    } catch (err) {
      setBulkError(describeApiError(err));
    } finally {
      setBulkLoading(false);
    }
  };

  return (
    <div className="space-y-4 max-w-[1100px]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Watchlist Management</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Continuous cross-reference feed for the alert engine · {items.filter((i) => i.active).length} active
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost text-xs" onClick={() => { setShowBulk(!showBulk); setShowForm(false); }}>
            <Upload size={14} /> Bulk Import
          </button>
          <button className="btn-primary" onClick={() => { setShowForm(!showForm); setShowBulk(false); }}>
            <Plus size={15} /> Add Entry
          </button>
        </div>
      </div>

      {error && (
        <InlineError message={error} onRetry={load} onDismiss={() => setError(null)} />
      )}
      {actionError && (
        <InlineError message={actionError} onDismiss={() => setActionError(null)} />
      )}

      {/* Single add form */}
      {showForm && (
        <form onSubmit={add} className="card p-4 grid grid-cols-2 md:grid-cols-3 gap-3">
          <select className="input" value={form.category}
            onChange={(e) => {
              const cat = e.target.value;
              setForm({ ...form, category: cat, subject_type: cat.includes("person") ? "person" : "vehicle" });
            }}>
            {Object.keys(CAT_LABEL).map((c) => (<option key={c} value={c}>{CAT_LABEL[c]}</option>))}
          </select>
          <input className="input" placeholder={form.subject_type === "vehicle" ? "Plate number (e.g. GJ 01 AB 1234)" : "Person name/ID"}
            value={form.identifier} onChange={(e) => setForm({ ...form, identifier: e.target.value })} required />
          <select className="input" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <input className="input" placeholder="FIR number" value={form.fir_number}
            onChange={(e) => setForm({ ...form, fir_number: e.target.value })} />
          <input className="input col-span-2" placeholder="Description" value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <button className="btn-primary col-span-2 md:col-span-3 justify-center">Save Entry</button>
        </form>
      )}

      {/* Bulk import panel */}
      {showBulk && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <FileText size={14} className="text-orange-400" /> Bulk Import
            </div>
            <button onClick={() => setShowBulk(false)} className="btn-icon"><X size={13} /></button>
          </div>
          <p className="text-xs text-slate-500">
            Paste CSV or JSON array below, or upload a file. CSV columns:{" "}
            <code className="font-mono text-orange-400">category, subject_type, identifier, severity, description, fir_number</code>
          </p>

          {/* File upload */}
          <div className="flex items-center gap-3">
            <label className="btn-ghost text-xs cursor-pointer">
              <Upload size={12} /> Choose File (.csv / .json)
              <input type="file" accept=".csv,.json,.txt" className="hidden" onChange={handleFileUpload} />
            </label>
            <button className="btn-ghost text-xs" onClick={() => setBulkText(SAMPLE_CSV)}>
              Load sample CSV
            </button>
          </div>

          <textarea
            className="input w-full font-mono text-xs"
            rows={8}
            placeholder={"Paste CSV or JSON array here…\n\nCSV example:\ncategory,subject_type,identifier,severity\nstolen_vehicle,vehicle,GJ 01 AB 1234,high"}
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
          />

          {bulkResult && (
            <div className={`text-xs rounded-lg px-3 py-2 ${bulkResult.created > 0 ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-amber-500/10 text-amber-400 border border-amber-500/20"}`}>
              ✓ Created {bulkResult.created} entries · Skipped {bulkResult.skipped} (duplicates or invalid)
            </div>
          )}
          {bulkError && (
            <InlineError message={`Bulk import failed: ${bulkError}`} onDismiss={() => setBulkError(null)} />
          )}

          <button className="btn-primary" disabled={bulkLoading || !bulkText.trim()} onClick={submitBulk}>
            {bulkLoading ? "Importing…" : "Import Now"}
          </button>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px]">
            <thead>
              <tr className="border-b border-control-800 bg-control-850">
                <th className="table-head">Category</th>
                <th className="table-head">Identifier</th>
                <th className="table-head">Severity</th>
                <th className="table-head">FIR</th>
                <th className="table-head">Description</th>
                <th className="table-head">Active</th>
                <th className="table-head"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-control-800/60">
              {items.map((w) => (
                <tr key={w.id} className="hover:bg-control-800/40">
                  <td className="table-cell">{CAT_LABEL[w.category] ?? w.category}</td>
                  <td className="table-cell font-mono font-semibold text-slate-200">{w.identifier}</td>
                  <td className="table-cell"><span className={`badge ${SEV_STYLE[w.severity]}`}>{w.severity}</span></td>
                  <td className="table-cell font-mono text-xs">{w.fir_number ?? "—"}</td>
                  <td className="table-cell text-xs max-w-[240px] truncate">{w.description ?? "—"}</td>
                  <td className="table-cell">
                    <button onClick={() => toggle(w)}
                      className={`w-9 h-5 rounded-full relative transition-colors ${w.active ? "bg-emerald-600" : "bg-control-700"}`}>
                      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${w.active ? "left-4" : "left-0.5"}`} />
                    </button>
                  </td>
                  <td className="table-cell">
                    <button onClick={() => remove(w.id)} className="text-slate-500 hover:text-red-400" title="Delete">
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {items.length === 0 && loading && !loadedOnce && (
          <div className="p-4 space-y-2">
            {[0, 1, 2].map((i) => <div key={i} className="skeleton h-9 rounded-lg" />)}
          </div>
        )}
        {items.length === 0 && loadedOnce && !error && (
          <div className="p-6 text-center text-sm text-slate-500 flex flex-col items-center gap-2">
            <ListChecks size={24} className="text-slate-600" />
            Watchlist is empty — add stolen vehicles or wanted persons to trigger live alerts.
          </div>
        )}
      </div>
    </div>
  );
}
