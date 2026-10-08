"use client";
import { useEffect, useState } from "react";
type Offer = { id: string; service_label: string; status: string; created_at: string };
export function SafetyFollowups() {
  const [offers, setOffers] = useState<Offer[]>([]); const [notice, setNotice] = useState(""); const [busy, setBusy] = useState(false);
  async function load() { const response = await fetch("/api/auth/safety-follow-ups", { cache: "no-store" }); if (!response.ok) throw new Error("Sign in to view support offers."); setOffers(await response.json()); }
  useEffect(() => { load().catch(error => setNotice(error.message)); }, []);
  async function choose(offer: Offer, status: string) { setBusy(true); try {
    const response = await fetch(`/api/auth/safety-choice?id=${offer.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, expected_status: offer.status }) });
    const data = await response.json(); if (!response.ok) throw new Error(data.detail ?? "The offer changed. Reload to see its status.");
    await load(); setNotice("Your choice was recorded. No service was automatically contacted.");
  } catch (error) { setNotice(error instanceof Error ? error.message : "Unable to record your choice."); } finally { setBusy(false); } }
  return <section className="space-y-3 rounded border p-4"><h2 className="text-xl font-semibold">Documented support offers</h2><p>These are human-reviewed follow-up offers, not diagnoses or emergency dispatches. Recording a choice does not contact a service or prove that care was received.</p><p role="status">{notice}</p><ul>{offers.map(offer => <li key={offer.id} className="my-3"><strong>{offer.service_label}</strong> - {offer.status}{offer.status !== "closed" && <div className="flex gap-3"><button disabled={busy} className="rounded border p-2" onClick={() => void choose(offer, "accepted")}>Record that I want this support</button><button disabled={busy} className="rounded border p-2" onClick={() => void choose(offer, "declined")}>Record that I decline</button></div>}</li>)}</ul>{!offers.length && <p>No documented support offers are available.</p>}</section>;
}
