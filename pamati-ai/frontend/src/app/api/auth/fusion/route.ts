import { NextRequest, NextResponse } from "next/server";
import { boundedBody, BodyError } from "@/lib/bounded-body";
export const dynamic = "force-dynamic";
export async function POST(request: NextRequest) {
  if (request.headers.get("origin") !== (process.env.AUTH_PUBLIC_URL ?? request.nextUrl.origin)) return NextResponse.json({ detail: "Access denied" }, { status: 403 });
  const token = request.cookies.get("pamati_access")?.value;
  if (!token) return NextResponse.json({ detail: "Please sign in or renew your session." }, { status: 401 });
  const session = request.nextUrl.searchParams.get("session") ?? "";
  if (!/^[0-9a-f-]{36}$/i.test(session)) return NextResponse.json({ detail: "Invalid session" }, { status: 422 });
  try {
    const upstream = await fetch(`${process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"}/api/v1/sessions/${session}/multimodal-analyses`, {
      method: "POST", body: await boundedBody(request), cache: "no-store", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, signal: AbortSignal.timeout(60000)
    });
    return NextResponse.json(await upstream.json(), { status: upstream.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) { return NextResponse.json({ detail: error instanceof BodyError ? error.message : "Fusion unavailable. Please retry." }, { status: error instanceof BodyError ? error.status : 503 }); }
}
