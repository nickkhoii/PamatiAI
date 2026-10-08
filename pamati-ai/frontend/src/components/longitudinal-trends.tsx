"use client";

import { useEffect, useState } from "react";

type Daily = { day: string; mean: number | null; interaction_count: number; observation_count: number; recorded_session_starts: number;
  baseline: { status: string; mean: number | null; day_count: number; interaction_count: number };
  delta_from_baseline: number | null; slope_per_day: number | null; change_direction: string | null;
  persistent_pattern: boolean; returning_toward_baseline: boolean; uncertainty: { standard_deviation: number | null } };
type Weekly = { week_start: string; mean: number | null; observed_days: number; missing_days: number; partial_week: boolean; interaction_count: number };
type Series = { id: string; dimension: string; model: string; model_version: string; created_at: string;
  summary: { daily: Daily[]; weekly: Weekly[]; experimental: boolean; configuration: { change_threshold: number; baseline_days: number; minimum_baseline_interactions: number; minimum_baseline_days: number }; algorithm: { identifier: string; version: string } } };

function number(value: number | null) { return value === null ? "Unavailable" : value.toFixed(3); }
function paths(values: (number | null)[], low: number, high: number) {
  let active = false;
  return values.map((value, i) => {
    if (value === null) { active = false; return ""; }
    const x = 50 + i * 600 / Math.max(1, values.length - 1);
    const y = 200 - (value - low) / (high - low) * 160;
    const command = `${active ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    active = true; return command;
  }).join(" ");
}

export function LongitudinalTrends({ reviewer = false }: { reviewer?: boolean }) {
  const [student, setStudent] = useState("");
  const [series, setSeries] = useState<Series[]>([]);
  const [selection, setSelection] = useState("");
  const [resolution, setResolution] = useState("daily");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  async function load(refresh = false) {
    if (reviewer && !/^[0-9a-f-]{36}$/i.test(student)) { setNotice("Enter the assigned student's record ID."); return; }
    setBusy(true); setNotice("");
    const query = reviewer ? `?student=${encodeURIComponent(student)}` : "";
    try {
      const response = await fetch(`/api/auth/longitudinal${query}`, { method: refresh ? "POST" : "GET",
        headers: refresh ? { "Content-Type": "application/json" } : undefined, body: refresh ? "{}" : undefined });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Trends are unavailable. Check your session and tracking permission.");
      setSeries(payload.series); setSelection(payload.series[0]?.id ?? "");
      if (!payload.series.length) setNotice("No eligible observations are available. Tracking is optional and needs completed analyses recorded with tracking permission.");
    } catch (error) { setSeries([]); setNotice(error instanceof Error ? error.message : "Unable to load trends."); }
    finally { setBusy(false); }
  }
  useEffect(() => { if (!reviewer) void load(); }, [reviewer]); // eslint-disable-line react-hooks/exhaustive-deps
  const chosen = series.find(s => s.id === selection);
  const daily = chosen?.summary.daily ?? [];
  const weekly = chosen?.summary.weekly ?? [];
  const values = resolution === "daily" ? daily.map(d => d.mean) : weekly.map(w => w.mean);
  const labels = resolution === "daily" ? daily.map(d => d.day) : weekly.map(w => w.week_start);
  const counts = resolution === "daily" ? daily.map(d => d.interaction_count) : weekly.map(w => w.interaction_count);
  const polarity = chosen?.dimension === "sentiment_polarity";
  return <section className="space-y-5 rounded border p-5">
    <h2 className="text-xl font-semibold">Sentiment and affect over time</h2>
    <p>Experimental estimates show changes across interactions. They are not diagnoses, a mental-health score, or evidence of crisis. Observable facial expression does not directly reveal internal feelings.</p>
    {reviewer && <label className="block">Assigned student record ID<input className="ml-3 rounded border p-2" value={student} disabled={busy} onChange={e => { setStudent(e.target.value); setSeries([]); }} /></label>}
    <div className="flex gap-3"><button disabled={busy} className="rounded border px-4 py-2" onClick={() => void load()}>Load saved trends</button><button disabled={busy} className="rounded border px-4 py-2" onClick={() => void load(true)}>Update last 90 days</button></div>
    <p role="status">{busy ? "Loading trends…" : notice}</p>
    {series.length > 0 && <>
      <label className="block">Observation series <select className="max-w-full rounded border p-2" value={selection} onChange={e => setSelection(e.target.value)}>{series.map(s => <option key={s.id} value={s.id}>{s.dimension.replaceAll("_", " ")} · {s.model}</option>)}</select></label>
      <label className="block">Summary interval <select className="rounded border p-2" value={resolution} onChange={e => setResolution(e.target.value)}><option value="daily">Daily</option><option value="weekly">Weekly (Monday start)</option></select></label>
      <p>Model estimates are shown in blue{resolution === "daily" ? "; the dashed gray line is your prior-history baseline" : ""}. Gaps mean no eligible data. Dates use UTC. {polarity ? "Polarity ranges from -1 to +1." : "Values are model probabilities, not measured emotional prevalence."}</p>
      <svg viewBox="0 0 700 250" className="w-full" role="img" aria-label="Observation trend with gaps for missing data. Numerical values are available in the table below.">
        <line x1="50" y1="200" x2="650" y2="200" stroke="#64748b" /><line x1="50" y1="40" x2="50" y2="200" stroke="#64748b" />
        <text x="10" y="45" fontSize="14">1</text><text x="10" y="200" fontSize="14">{polarity ? "-1" : "0"}</text>
        {resolution === "daily" && <path d={paths(daily.map(d => d.baseline.mean), polarity ? -1 : 0, 1)} stroke="#64748b" strokeWidth="2" strokeDasharray="6 4" fill="none" />}
        <path d={paths(values, polarity ? -1 : 0, 1)} stroke="#2563eb" strokeWidth="2.5" fill="none" />
        {values.map((value, i) => value !== null && <circle key={i} cx={50 + i * 600 / Math.max(1, values.length - 1)} cy={200 - (value - (polarity ? -1 : 0)) / (polarity ? 2 : 1) * 160} r="3" fill="#2563eb"><title>{labels[i]}: {number(value)}</title></circle>)}
        <text x="50" y="230" fontSize="13">{labels[0]}</text><text x="650" y="230" textAnchor="end" fontSize="13">{labels.at(-1)}</text>
      </svg>
      <h3 className="font-semibold">Analyzed interaction frequency</h3><p>Counts describe available analyzed sessions, not wellbeing or engagement quality. A session spanning days can appear on multiple days; weekly counts use distinct sessions.</p>
      <svg viewBox="0 0 700 120" className="w-full" role="img" aria-label="Analyzed interaction counts by summary interval; exact counts are in the table.">{counts.map((count, i) => <rect key={i} x={50 + i * 600 / Math.max(1, counts.length)} y={100 - count / Math.max(1, ...counts) * 80} width={Math.max(1, 600 / Math.max(1, counts.length) - 2)} height={count / Math.max(1, ...counts) * 80} fill="#475569"><title>{labels[i]}: {count} interactions</title></rect>)}</svg>
      {chosen && <p>Baseline: previous {chosen.summary.configuration.baseline_days} days, requiring at least {chosen.summary.configuration.minimum_baseline_interactions} interaction-day segments across {chosen.summary.configuration.minimum_baseline_days} days. Change threshold: {chosen.summary.configuration.change_threshold} (experimental). Method: {chosen.summary.algorithm.identifier}, version {chosen.summary.algorithm.version}. Model version: {chosen.model_version}. Updated {chosen.created_at.replace("T", " ")} UTC.</p>}
      <details><summary className="cursor-pointer underline">View values, history coverage and uncertainty</summary><div className="overflow-x-auto"><table className="w-full text-left"><caption className="py-3">Descriptive spread is not a calibrated confidence interval. Missing values are unavailable, never zero-filled.</caption><thead><tr><th>Date (UTC)</th><th>Mean estimate</th><th>Interactions</th>{resolution === "daily" ? <><th>Baseline</th><th>Change</th><th>Spread</th><th>Pattern</th></> : <><th>Observed days</th><th>Missing days</th></>}</tr></thead><tbody>{resolution === "daily" ? daily.map(d => <tr key={d.day}><td>{d.day}</td><td>{number(d.mean)}</td><td>{d.interaction_count}</td><td>{d.baseline.status === "available" ? number(d.baseline.mean) : "Insufficient history"}<br />{d.baseline.day_count} days; {d.baseline.interaction_count} segments</td><td>{number(d.delta_from_baseline)}</td><td>{number(d.uncertainty.standard_deviation)}</td><td>{d.mean === null ? "No observation" : d.baseline.status !== "available" ? "Insufficient history" : d.persistent_pattern ? "Persistent difference from baseline" : d.returning_toward_baseline ? "Closer to prior baseline" : d.change_direction ? "Difference from baseline" : "No threshold finding"}</td></tr>) : weekly.map(w => <tr key={w.week_start}><td>{w.week_start}{w.partial_week ? " (partial)" : ""}</td><td>{number(w.mean)}</td><td>{w.interaction_count}</td><td>{w.observed_days}</td><td>{w.missing_days}</td></tr>)}</tbody></table></div></details>
      <p>Several consistent estimates can still share model errors. Language, cultural context, sarcasm, domain shift and recording quality affect interpretation. A baseline describes prior observations; it does not establish a healthy state. Request human discussion if an estimate seems wrong.</p>
    </>}
  </section>;
}
