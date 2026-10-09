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
    calls.push({ path: request.url, method: request.method, body: body ? request.headers["content-type"]?.startsWith("audio/") ? { bytes: Buffer.byteLength(body) } : JSON.parse(body) : {}, authorization: request.headers.authorization });
    response.setHeader("Content-Type", "application/json");
    if (["/api/v1/auth/login", "/api/v1/auth/refresh"].includes(request.url)) {
      response.end(JSON.stringify({ access_token: "test-access-secret", refresh_token: "test-refresh-secret", expires_in: 900 }));
    } else if (request.url === "/api/v1/me") {
      response.end(JSON.stringify({ id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email: "test@example.com", display_name: "Test", roles: ["STUDENT"] }));
    } else if (request.url.startsWith("/api/v1/dashboard/")) {
      response.end(JSON.stringify({ items: [], total: 0, page: 1, limit: 12 }));
    } else if (request.url.startsWith("/api/v1/notifications?") || request.url.includes("/audio-analyses")) {
      response.end(JSON.stringify({ items: [], total: 0, unread_count: 0, status: "completed" }));
    } else if (request.url.startsWith("/api/v1/conversations/") && request.method !== "DELETE") {
      response.end(JSON.stringify({ messages: [], next_offset: null }));
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
    const inbox = await fetch(origin + "/api/auth/notifications?unread=true&page=2", { headers: { Cookie: cookieHeader } });
    assert.equal(inbox.status, 200);
    assert.equal(calls.at(-1).path, "/api/v1/notifications?page=2&unread=true");
    const event = "support:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:requested";
    const beforeForged = calls.length;
    const forgedRead = await fetch(origin + `/api/auth/notifications?id=${event}`, { method: "POST", headers: { Origin: "https://attacker.example", Cookie: cookieHeader } });
    assert.equal(forgedRead.status, 403); assert.equal(calls.length, beforeForged);
    const read = await fetch(origin + `/api/auth/notifications?id=${event}`, { method: "POST", headers: { Origin: origin, Cookie: cookieHeader } });
    assert.equal(read.status, 200); assert.equal(calls.at(-1).method, "POST");
    const mediaPath = "/api/auth/media?session=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa&modality=audio";
    const beforeInvalidMedia = calls.length;
    for (const [headers, body, status] of [
      [{ Origin: "https://attacker.example", Cookie: cookieHeader, "Content-Type": "audio/wav" }, "test", 403],
      [{ Origin: origin, Cookie: cookieHeader, "Content-Type": "text/html" }, "test", 415],
      [{ Origin: origin, Cookie: cookieHeader, "Content-Type": "audio/wav" }, "x".repeat(3000001), 413]
    ]) {
      assert.equal((await fetch(origin + mediaPath, { method: "POST", headers, body })).status, status);
    }
    assert.equal(calls.length, beforeInvalidMedia);
    const media = await fetch(origin + mediaPath, { method: "POST", headers: { Origin: origin, Cookie: cookieHeader, "Content-Type": "audio/wav" }, body: "RIFFtest" });
    assert.equal(media.status, 200);
    assert.equal(calls.at(-1).path, "/api/v1/sessions/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/audio-analyses");
    assert.equal(calls.at(-1).authorization, "Bearer test-access-secret");
    const profile = await fetch(origin + "/api/auth/profile", { headers: { Cookie: cookieHeader } });
    assert.equal(profile.status, 200);
    assert.equal(calls.at(-1).authorization, "Bearer test-access-secret");
    const dashboard = await fetch(origin + "/api/auth/dashboard?role=STUDENT&collection=conversations&q=reflection&page=2&start=2026-10-01", { headers: { Cookie: cookieHeader } });
    assert.equal(dashboard.status, 200);
    assert.equal(calls.at(-1).path, "/api/v1/dashboard/STUDENT/conversations?q=reflection&start=2026-10-01&page=2");
    const beforeForgedDashboard = calls.length;
    const forgedDashboard = await fetch(origin + "/api/auth/dashboard?op=check-in", { method: "POST", headers: { Origin: "https://attacker.example", Cookie: cookieHeader }, body: "{}" });
    assert.equal(forgedDashboard.status, 403);
    assert.equal(calls.length, beforeForgedDashboard);
    const beforeOversize = calls.length;
    for (const path of ["/api/auth/login", "/api/auth/dashboard?op=check-in"]) {
      const stream = new ReadableStream({ start(controller) {
        controller.enqueue(new TextEncoder().encode(" ".repeat(20000)));
        controller.enqueue(new TextEncoder().encode(" ".repeat(20000)));
        controller.close();
      } });
      const oversized = await fetch(origin + path, { method: "POST", duplex: "half",
        headers: { Origin: origin, Cookie: cookieHeader, "Content-Type": "application/json" }, body: stream });
      assert.equal(oversized.status, 413);
      assert.equal(oversized.headers.get("cache-control"), "no-store");
    }
    assert.equal(calls.length, beforeOversize);
    const checkin = await fetch(origin + "/api/auth/dashboard?op=check-in", { method: "POST", headers: { Origin: origin, Cookie: cookieHeader, "Content-Type": "application/json" }, body: JSON.stringify({ feeling: "mixed" }) });
    assert.equal(checkin.status, 200);
    assert.equal(calls.at(-1).path, "/api/v1/dashboard/check-ins");
    assert.deepEqual(calls.at(-1).body, { feeling: "mixed" });
    for (const route of ["student", "counselor", "admin"]) {
      const page = await fetch(origin + "/" + route);
      assert.equal(page.status, 200);
      const html = await page.text();
      assert.match(html, /aria-label="Dashboard sections"/);
      const policy = page.headers.get("content-security-policy");
      assert.match(policy, /frame-ancestors 'none'/);
      assert.match(policy, /script-src .*'strict-dynamic'/);
      assert.doesNotMatch(policy, /script-src[^;]*'unsafe-inline'/);
      const nonce = policy.match(/'nonce-([^']+)'/)[1];
      for (const script of html.matchAll(/<script\b[^>]*>/g)) assert.ok(script[0].includes(`nonce="${nonce}"`));
      const second = await fetch(origin + "/" + route);
      assert.notEqual(second.headers.get("content-security-policy"), policy);
    }
    const records = await fetch(origin + "/api/auth/records?category=research&student_id=bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", { headers: { Cookie: cookieHeader } });
    assert.equal(records.status, 200);
    assert.equal(calls.at(-1).path, "/api/v1/students/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/records?category=research&offset=0");
    const consent = await fetch(origin + "/api/auth/consent", { method: "POST", headers: { Origin: origin, Cookie: cookieHeader, "Content-Type": "application/json" }, body: JSON.stringify({ policy_version: "test", text_processing: true, audio_processing: false }) });
    assert.equal(consent.status, 200);
    assert.equal(calls.at(-1).method, "PUT");
    assert.equal(calls.at(-1).path, "/api/v1/students/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/consent");
    assert.equal(calls.at(-1).body.audio_processing, false);
    const chatPage = await fetch(origin + "/student/chat");
    const chatHTML = await chatPage.text();
    assert.equal(chatPage.status, 200);
    assert.match(chatHTML, /Your reflection space/);
    assert.match(chatHTML, /aria-label="Conversation history"/);
    assert.match(chatHTML, /id="chat-message"/);
    const studentHeaders = { Origin: origin, Cookie: cookieHeader, "Content-Type": "application/json" };
    const created = await fetch(origin + "/api/auth/new-conversation?student_id=bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", { method: "POST", headers: studentHeaders, body: "{}" });
    assert.equal(created.status, 200);
    assert.equal(calls.at(-1).path, "/api/v1/students/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/conversations");
    assert.equal(calls.at(-1).method, "POST");
    const conversationId = "cccccccc-cccc-cccc-cccc-cccccccccccc";
    const turnBody = { request_id: "dddddddd-dddd-dddd-dddd-dddddddddddd", text: "Study stress" };
    const turn = await fetch(origin + `/api/auth/chat-turn?id=${conversationId}`, { method: "POST", headers: studentHeaders, body: JSON.stringify(turnBody) });
    assert.equal(turn.status, 200);
    assert.equal(calls.at(-1).path, `/api/v1/conversations/${conversationId}/messages`);
    assert.deepEqual(calls.at(-1).body, turnBody);
    assert.equal(calls.at(-1).authorization, "Bearer test-access-secret");
    const beforeForgedTurn = calls.length;
    const forgedTurn = await fetch(origin + `/api/auth/chat-turn?id=${conversationId}`, { method: "POST", headers: { ...studentHeaders, Origin: "https://attacker.example" }, body: JSON.stringify(turnBody) });
    assert.equal(forgedTurn.status, 403);
    assert.equal(calls.length, beforeForgedTurn);
    const conversation = await fetch(origin + `/api/auth/conversation?id=${conversationId}&offset=100`, { headers: { Cookie: cookieHeader } });
    assert.equal(conversation.status, 200);
    assert.equal(calls.at(-1).path, `/api/v1/conversations/${conversationId}?offset=100`);
    const hidden = await fetch(origin + `/api/auth/hide-conversation?id=${conversationId}`, { method: "POST", headers: studentHeaders, body: "{}" });
    assert.equal(hidden.status, 200);
    assert.equal(calls.at(-1).method, "DELETE");
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
