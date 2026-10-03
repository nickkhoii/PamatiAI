import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import test from "node:test";

const listen = server => new Promise(resolve => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
const close = server => new Promise(resolve => server.close(resolve));

test("browser gateway checks Origin, protects tokens, and revokes expired-access sessions", { skip: !process.env.RUN_AUTH_GATEWAY_TESTS }, async () => {
  const calls = [];
  const backend = createServer(async (request, response) => {
    let body = "";
    for await (const chunk of request) body += chunk;
    calls.push({ path: request.url, method: request.method, body: body ? JSON.parse(body) : {}, authorization: request.headers.authorization });
    response.setHeader("Content-Type", "application/json");
    if (["/api/v1/auth/login", "/api/v1/auth/refresh"].includes(request.url)) {
      response.end(JSON.stringify({ access_token: "test-access-secret", refresh_token: "test-refresh-secret", expires_in: 900 }));
    } else if (request.url === "/api/v1/me") {
      response.end(JSON.stringify({ id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email: "test@example.com", display_name: "Test", roles: ["STUDENT"] }));
    } else if (request.url.startsWith("/api/v1/students/") && request.method !== "DELETE") {
      response.end(JSON.stringify({ records: [], next_offset: null }));
    } else { response.writeHead(204); response.end(); }
  });
  const backendPort = await listen(backend);
  const reservation = createServer();
  const frontendPort = await listen(reservation);
  await close(reservation);
  const origin = `http://localhost:${frontendPort}`;
  const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "-p", String(frontendPort)], {
    env: { ...process.env, NODE_ENV: "production", NEXT_TELEMETRY_DISABLED: "1", API_INTERNAL_URL: `http://127.0.0.1:${backendPort}`, AUTH_PUBLIC_URL: origin },
    stdio: ["ignore", "ignore", "ignore"], windowsHide: true
  });
  try {
    let ready = false;
    for (let i = 0; i < 60; i++) {
      try { if ((await fetch(origin + "/auth/login")).ok) { ready = true; break; } } catch {}
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    assert.equal(ready, true, "Next.js production server should start after npm run build");
    const denied = await fetch(origin + "/api/auth/login", { method: "POST", headers: { Origin: "https://attacker.example", "Content-Type": "application/json" }, body: "{}" });
    assert.equal(denied.status, 403);
    assert.equal(calls.length, 0);
    const login = await fetch(origin + "/api/auth/login", { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify({ email: "test@example.com", password: "test-password" }) });
    assert.equal(login.status, 200);
    const payload = await login.text();
    assert.equal(payload.includes("test-access-secret"), false);
    assert.equal(payload.includes("test-refresh-secret"), false);
    const cookies = login.headers.getSetCookie();
    assert.equal(cookies.length, 2);
    for (const cookie of cookies) {
      assert.match(cookie, /HttpOnly/i); assert.match(cookie, /Secure/i); assert.match(cookie, /SameSite=strict/i);
    }
    const cookieHeader = cookies.map(cookie => cookie.split(";")[0]).join("; ");
    const profile = await fetch(origin + "/api/auth/profile", { headers: { Cookie: cookieHeader } });
    assert.equal(profile.status, 200);
    assert.equal(calls.at(-1).authorization, "Bearer test-access-secret");
    const records = await fetch(origin + "/api/auth/records?category=research&student_id=bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", { headers: { Cookie: cookieHeader } });
    assert.equal(records.status, 200);
    assert.equal(calls.at(-1).path, "/api/v1/students/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/records?category=research&offset=0");
    const consent = await fetch(origin + "/api/auth/consent", { method: "POST", headers: { Origin: origin, Cookie: cookieHeader, "Content-Type": "application/json" }, body: JSON.stringify({ policy_version: "test", text_processing: true, audio_processing: false }) });
    assert.equal(consent.status, 200);
    assert.equal(calls.at(-1).method, "PUT");
    assert.equal(calls.at(-1).path, "/api/v1/students/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/consent");
    assert.equal(calls.at(-1).body.audio_processing, false);
    const withdrawn = await fetch(origin + "/api/auth/withdraw-consent", { method: "POST", headers: { Origin: origin, Cookie: cookieHeader, "Content-Type": "application/json" }, body: "{}" });
    assert.equal(withdrawn.status, 200);
    assert.equal(calls.at(-1).method, "DELETE");
    const refreshed = await fetch(origin + "/api/auth/refresh", { method: "POST", headers: { Origin: origin, Cookie: cookieHeader, "Content-Type": "application/json" }, body: JSON.stringify({ token: "client-forged-value" }) });
    assert.equal(refreshed.status, 200);
    assert.equal(calls.at(-1).body.token, "test-refresh-secret");
    const logout = await fetch(origin + "/api/auth/logout", { method: "POST", headers: { Origin: origin, Cookie: "pamati_refresh=test-refresh-secret", "Content-Type": "application/json" }, body: "{}" });
    assert.equal(logout.status, 200);
    assert.equal(calls.at(-1).path, "/api/v1/auth/logout-session");
    assert.equal(calls.at(-1).body.token, "test-refresh-secret");
    assert.ok(logout.headers.getSetCookie().every(cookie => /Max-Age=0/i.test(cookie)));
  } finally {
    child.kill();
    backend.closeAllConnections();
    await close(backend);
  }
});
