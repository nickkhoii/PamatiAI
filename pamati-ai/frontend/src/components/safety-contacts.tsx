"use client";
import { useEffect, useState } from "react";

type Resource = { id: string; label: string; kind: string; jurisdiction: string; institution: string; phone: string; url: string; availability: string };
export function SafetyContacts() {
  const [resources, setResources] = useState<Resource[]>([]);
  const [notice, setNotice] = useState("");
  useEffect(() => { fetch("/api/auth/safety-resources", { cache: "no-store" }).then(async response => {
    if (!response.ok) throw new Error(); setResources((await response.json()).resources);
  }).catch(() => setNotice("The configured directory is unavailable. Use appropriate local emergency services or a trusted person if you need immediate help.")); }, []);
  return <aside className="rounded border border-slate-300 bg-slate-50 p-4"><h2 className="font-semibold">Immediate help and local support</h2><p>If you or someone else may be in immediate danger, contact local emergency services or go to the nearest emergency department. If possible, reach a trusted person who can stay with you. Do not wait for this chat or a trend estimate.</p><p>PamatiAI does not dispatch help or guarantee immediate human review.</p><p role="status">{notice}</p><ul>{resources.map(r => <li key={r.id} className="mt-2"><strong>{r.label}</strong> ({r.institution}; {r.jurisdiction}) {r.phone && <a className="underline" href={`tel:${r.phone.replace(/[ ()-]/g, "")}`}>{r.phone}</a>} {r.url && <a className="underline" href={r.url} rel="noopener noreferrer" target="_blank">Contact information</a>}<br />{r.availability}</li>)}</ul>{!resources.length && !notice && <p>No institution-configured contact directory is available here. Contact resources appropriate to your current location.</p>}</aside>;
}
