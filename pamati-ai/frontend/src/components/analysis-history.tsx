"use client";
import { useEffect, useState } from "react";
type Analysis = { id: string; session_id: string; modality: string; status: string; model: string; model_version: string; created_at: string; limitations: string[] };
type Page = { items: Analysis[]; total: number; page: number; limit: number };
export function AnalysisHistory() {
  const [data, setData] = useState<Page | null>(null); const [page, setPage] = useState(1);
  const [modality, setModality] = useState(""); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0); const [selected, setSelected] = useState<Analysis[]>([]);
  useEffect(() => {
    const controller = new AbortController(); setBusy(true); setError("");
    const query = new URLSearchParams({ page: String(page), modality });
    fetch(`/api/auth/analyses?${query}`, { cache: "no-store", signal: controller.signal }).then(async r => {
      const value = await r.json(); if (!r.ok) throw new Error(value.detail ?? "Unable to load analyses."); return value;
    }).then(setData).catch(e => { if (e.name !== "AbortError") setError(e.message); }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [page, modality, revision]);
  async function combine() {
    if (selected.length < 2) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`/api/auth/fusion?session=${encodeURIComponent(selected[0].session_id)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_inference_ids: selected.map(r => r.id) }) });
      const value = await response.json(); if (!response.ok) throw new Error(value.detail ?? "Unable to combine these records.");
      setNotice(`Combined research record saved: ${value.status}. This is an AI-generated observation, not a human-reviewed assessment.`);
      setSelected([]); setRevision(r => r + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="space-y-3" aria-busy={busy}><h2 className="text-xl font-semibold">Saved AI-generated observations</h2><p>These are experimental research outputs, not diagnoses or well-being ratings. Audio/visual baselines can abstain from estimating affect. Detailed machine-readable records are available in your personal download.</p>
    <label>Modality <select value={modality} onChange={e => { setModality(e.target.value); setPage(1); }}>{["", "text", "audio", "visual", "multimodal"].map(m => <option key={m} value={m}>{m || "All modalities"}</option>)}</select></label><button disabled={busy} onClick={() => setRevision(r => r + 1)}>Reload saved records</button>
    {busy && <p role="status">Loading saved observations…</p>}{error && <p role="alert">{error}</p>}<p role="status">{notice}</p>
    {!busy && !error && !data?.items.length && <p>No available analysis records match this modality.</p>}
    {!busy && !error && <ul className="space-y-3">{data?.items.map(row => {
      const chosen = selected.some(s => s.id === row.id);
      const eligible = row.status === "completed" && row.modality !== "multimodal";
      const incompatible = selected.length >= 3 || selected.some(s => s.session_id !== row.session_id || s.modality === row.modality);
      return <li key={row.id} className="rounded border p-4"><h3>{row.modality}: {row.status}</h3><p>{row.model}, version {row.model_version} · {new Date(row.created_at + "Z").toLocaleString()}</p><p>Reference: {row.id}</p>
        {row.limitations?.length > 0 && <details><summary>Research limitations</summary><ul>{row.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></details>}
        {eligible && <label><input type="checkbox" checked={chosen} disabled={busy || (!chosen && incompatible)} onChange={() => setSelected(s => chosen ? s.filter(r => r.id !== row.id) : [...s, row])} /> Select for optional modality comparison</label>}</li>;
    })}</ul>}
    <nav aria-label="Analysis pagination"><button disabled={busy || page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button><span> Page {page} </span><button disabled={busy || !data || page * data.limit >= data.total} onClick={() => setPage(p => p + 1)}>Next</button></nav>
    <p>Select two or three different modalities from the same interaction. The server rechecks consent, source availability and compatibility before combining them.</p>
    {selected.length > 0 && <ul>{selected.map(r => <li key={r.id}>{r.modality}: {r.model} <button disabled={busy} onClick={() => setSelected(s => s.filter(a => a.id !== r.id))}>Remove selection</button></li>)}</ul>}
    <button disabled={busy || selected.length < 2} onClick={combine}>Combine selected modalities</button>
  </section>;
}
