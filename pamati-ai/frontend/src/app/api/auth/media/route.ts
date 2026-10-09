import { NextRequest, NextResponse } from "next/server";
import { boundedBytes, BodyError } from "@/lib/bounded-body";
export const dynamic = "force-dynamic";
export async function POST(request: NextRequest) {
  if (request.headers.get("origin") !== (process.env.AUTH_PUBLIC_URL ?? request.nextUrl.origin)) return NextResponse.json({ detail: "Access denied" }, { status: 403 });
  const token = request.cookies.get("pamati_access")?.value;
  if (!token) return NextResponse.json({ detail: "Please sign in or renew your session." }, { status: 401 });
  const session = request.nextUrl.searchParams.get("session") ?? "";
  const modality = request.nextUrl.searchParams.get("modality");
  if (!/^[0-9a-f-]{36}$/i.test(session) || !["audio", "visual"].includes(modality ?? "")) return NextResponse.json({ detail: "Invalid research upload" }, { status: 422 });
  const type = request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() ?? "";
  if (!(modality === "audio" ? ["audio/wav", "audio/x-wav", "audio/wave"] : ["image/bmp", "image/x-ms-bmp", "application/json"]).includes(type)) return NextResponse.json({ detail: "Unsupported research upload format" }, { status: 415 });
  try {
    const bytes = await boundedBytes(request, 3000000);
    const upstream = await fetch(`${process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"}/api/v1/sessions/${session}/${modality}-analyses`, {
      method: "POST", body: Buffer.from(bytes), cache: "no-store", headers: { Authorization: `Bearer ${token}`, "Content-Type": type }, signal: AbortSignal.timeout(60000)
    });
    return NextResponse.json(await upstream.json(), { status: upstream.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) { return NextResponse.json({ detail: error instanceof BodyError ? error.message : "Research processing unavailable. Please retry." }, { status: error instanceof BodyError ? error.status : 503 }); }
}
