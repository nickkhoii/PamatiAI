import { NextRequest, NextResponse } from "next/server";
import { boundedBody, BodyError } from "@/lib/bounded-body";
export const dynamic = "force-dynamic";
const uuid = /^[0-9a-f-]{36}$/i;
function target(request: NextRequest, mutation: boolean) {
  const p = request.nextUrl.searchParams;
  const id = p.get("id") ?? "";
  if (mutation) {
    const op = p.get("op");
    if (op === "check-in") return ["dashboard/check-ins", "POST"];
    if (op === "remove-check-in" && uuid.test(id)) return [`dashboard/check-ins/${id}`, "DELETE"];
    if (op === "resources") return ["dashboard/resources", "PUT"];
    if (["activation", "role"].includes(op ?? "") && uuid.test(id)) return [`admin/users/${id}/${op}`, "PATCH"];
    if (op === "setting" && ["data_retention", "raw_media_retention"].includes(id)) return [`admin/settings/${id}`, "PUT"];
    if (op === "assignment") return ["admin/assignments", "PUT"];
    if (op === "support-status" && uuid.test(id)) return [`dashboard/support/${id}`, "PATCH"];
    return null;
  }
  if (p.get("op") === "observations" && uuid.test(id)) {
    const dates = new URLSearchParams();
    for (const key of ["start", "end"]) if (p.get(key)) dates.set(key, p.get(key)!);
    return [`dashboard/observations/students/${id}?${dates}`, "GET"];
  }
  const role = p.get("role") ?? "";
  const collection = p.get("collection") ?? "";
  if (!["STUDENT", "COUNSELOR", "ADMIN"].includes(role) || !["conversations", "check-ins", "support", "resources", "cases", "queue", "reviews", "referrals", "users", "roles", "models", "audit", "settings"].includes(collection)) return null;
  const query = new URLSearchParams();
  for (const key of ["q", "status", "start", "end", "page", "limit", "student"]) if (p.get(key)) query.set(key, p.get(key)!);
  return [`dashboard/${role}/${collection}?${query}`, "GET"];
}
async function proxy(request: NextRequest, mutation: boolean) {
  if (mutation && request.headers.get("origin") !== (process.env.AUTH_PUBLIC_URL ?? request.nextUrl.origin)) return NextResponse.json({ detail: "Access denied" }, { status: 403 });
  const token = request.cookies.get("pamati_access")?.value;
  if (!token) return NextResponse.json({ detail: "Please sign in or renew your session." }, { status: 401 });
  const path = target(request, mutation);
  if (!path) return NextResponse.json({ detail: "Not found" }, { status: 404 });
  try {
    const body = mutation ? await boundedBody(request) : undefined;
    if (body && new TextEncoder().encode(body).length > 32768) return NextResponse.json({ detail: "Request too large" }, { status: 413 });
    const upstream = await fetch(`${process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"}/api/v1/${path[0]}`, {
      method: path[1], body: path[1] === "DELETE" ? undefined : body, cache: "no-store",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, signal: AbortSignal.timeout(15000)
    });
    return NextResponse.json(upstream.status === 204 ? {} : await upstream.json(), { status: upstream.status === 204 ? 200 : upstream.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) { return NextResponse.json({ detail: error instanceof BodyError ? error.message : "Service temporarily unavailable. Please retry." }, { status: error instanceof BodyError ? error.status : 503 }); }
}
export const GET = (request: NextRequest) => proxy(request, false);
export const POST = (request: NextRequest) => proxy(request, true);
