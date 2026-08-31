import { useEffect, useState } from "react";
import { Plus, Trash2, ListChecks } from "lucide-react";
import { api } from "../lib/api";

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

export default function Watchlist() {
  const [items, setItems] = useState<Entry[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    category: "stolen_vehicle",
    subject_type: "vehicle",
    identifier: "",
    description: "",
    severity: "high",
    fir_number: "",
  });

  const load = () => {
    api<{ items: Entry[] }>("/watchlist").then((r) => setItems(r.items)).catch(() => undefined);
  };
  useEffect(load, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api("/watchlist", {
        method: "POST",
        body: JSON.stringify({ ...form, description: form.description || null, fir_number: form.fir_number || null }),
      });
      setShowForm(false);
      setForm({ ...form, identifier: "", description: "", fir_number: "" });
      load();
    } catch (err) {
      alert(err);
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Remove this watchlist entry?")) return;
    await api(`/watchlist/${id}`, { method: "DELETE" });
    load();
  };

  const toggle = async (entry: Entry) => {
    await api(`/watchlist/${entry.id}`, { method: "PATCH", body: JSON.stringify({ active: !entry.active }) });
    load();
  };

  return (
    <div className="space-y-4 max-w-[1100px]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Watchlist Management</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Continuous cross-reference feed for the alert engine
          </p>
        </div>
        <button className="btn-primary" onClick={() => setShowForm(!showForm)}>
          <Plus size={15} /> Add Entry
        </button>
      </div>

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
        {items.length === 0 && (
          <div className="p-6 text-center text-sm text-slate-500 flex flex-col items-center gap-2">
            <ListChecks size={24} className="text-slate-600" />
            Watchlist is empty — add stolen vehicles or wanted persons to trigger live alerts.
          </div>
        )}
      </div>
    </div>
  );
}
