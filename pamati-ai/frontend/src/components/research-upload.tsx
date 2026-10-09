"use client";
import { useState } from "react";
export function ResearchUpload({ session }: { session: string }) {
  const [modality, setModality] = useState("audio"); const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setError(""); setNotice("");
    if (!file || file.size > 3000000) { setError("Choose a file of at most 3 MB."); return; }
    setBusy(true);
    try {
      const response = await fetch(`/api/auth/media?session=${encodeURIComponent(session)}&modality=${modality}`, {
        method: "POST", headers: { "Content-Type": modality === "audio" ? "audio/wav" : file.name.toLowerCase().endsWith(".json") ? "application/json" : "image/bmp" }, body: file
      });
      const value = await response.json(); if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Unable to process this upload.");
      setNotice(`Research upload processed (${value.status ?? "recorded"}). This is an AI-generated observation, not a diagnosis. View eligible results in your records.`);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <details className="mt-4"><summary>Optional research upload</summary><form onSubmit={submit} className="space-y-3 p-3">
    <p>Separate current consent and an enabled institutional processor are required. No microphone or camera is activated. Acoustic and no-expression baselines do not provide validated emotion recognition. Raw images are not retained; audio retention follows your separate consent settings.</p>
    <label className="block">Modality<select disabled={busy} value={modality} onChange={e => { setModality(e.target.value); setFile(null); setNotice(""); }}><option value="audio">Audio: mono PCM WAV, up to 30 seconds</option><option value="visual">Visual: 24-bit BMP or documented JSON BMP frames</option></select></label>
    <label className="block">Research file (maximum 3 MB)<input key={modality} disabled={busy} type="file" accept={modality === "audio" ? ".wav" : ".bmp,.json"} onChange={e => { setFile(e.target.files?.[0] ?? null); setNotice(""); }} required /></label>
    <button disabled={busy || !file} type="submit">{busy ? "Processing upload…" : "Submit optional research upload"}</button>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice} <a href="/student/records">Open my records</a></p>}
  </form></details>;
}
