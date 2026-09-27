import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import net from "node:net";
import { WebSocket } from "ws";

test("gateway enforces auth, origin, settings, single session, snapshot and cleanup", async (t) => {
  const reservation = net.createServer();
  reservation.listen(0, "127.0.0.1");
  await once(reservation, "listening");
  const port = reservation.address().port;
  await new Promise((r) => reservation.close(r));
  const origin = `http://localhost:${port}`;
  const child = spawn(process.execPath, ["server.mjs"], {
    cwd: new URL("..", import.meta.url),
    env: {
      ...process.env,
      PORT: String(port),
      JEV_PUBLIC_ORIGIN: origin,
      JEV_ACCESS_CODE: "test-only-secret",
      JEV_MODE: "mock",
      JEV_GRAPH_COMMAND: "",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  t.after(() => child.kill("SIGTERM"));
  await once(child.stdout, "data");
  const post = (route, data, cookie, from = origin) =>
    fetch(origin + route, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Origin: from,
        ...(cookie ? { Cookie: cookie } : {}),
      },
      body: JSON.stringify(data),
    });
  assert.equal((await post("/api/session", {})).status, 401);
  assert.equal(
    (
      await post(
        "/api/login",
        { code: "test-only-secret" },
        null,
        "http://evil.test",
      )
    ).status,
    403,
  );
  assert.equal((await post("/api/login", { code: "incorrect" })).status, 401);
  const login = await post("/api/login", { code: "test-only-secret" });
  assert.equal(login.status, 200);
  const cookie = login.headers.get("set-cookie").split(";")[0];
  assert.match(login.headers.get("set-cookie"), /HttpOnly/);
  assert.equal(
    (
      await post(
        "/api/session",
        { settings: { "provider.api_key": "bad" } },
        cookie,
      )
    ).status,
    400,
  );
  const created = await post(
    "/api/session",
    { settings: { "start.enabled": true } },
    cookie,
  );
  assert.equal(created.status, 200);
  const firstSession = await created.json();
  assert.match(firstSession.id, /^[a-f0-9]{32}$/);
  assert.equal((await post("/api/session", {}, cookie)).status, 409);
  assert.equal(
    (
      await post(
        "/api/end",
        { session_id: "00000000000000000000000000000000" },
        cookie,
      )
    ).status,
    200,
  );
  assert.equal((await post("/api/session", {}, cookie)).status, 409);
  const ws = new WebSocket(`ws://localhost:${port}/ws`, {
    headers: { Origin: origin, Cookie: cookie },
  });
  const next = new Promise((resolve) =>
    ws.on("message", (message) => {
      if (JSON.parse(message).data?.type === "state.snapshot")
        resolve([message]);
    }),
  );
  await once(ws, "open");
  ws.send(
    JSON.stringify({
      type: "data",
      name: "jev_control",
      data: { action: "snapshot" },
    }),
  );
  const [message] = await next;
  const event = JSON.parse(message);
  assert.equal(event.name, "jev_event");
  assert.equal(event.data.type, "state.snapshot");
  assert.equal(event.data.payload.mode, "mock");
  const closed = once(ws, "close");
  ws.send(
    JSON.stringify({ type: "data", name: "arbitrary_command", data: {} }),
  );
  await closed;
  assert.equal(
    (await post("/api/end", { session_id: firstSession.id }, cookie)).status,
    200,
  );
  const secondSession = await (await post("/api/session", {}, cookie)).json();
  for (const invalid of [
    {},
    { session_id: "" },
    { session_id: 7 },
    { session_id: "not-an-id" },
  ])
    assert.equal((await post("/api/end", invalid, cookie)).status, 400);
  // S1 cleanup succeeded but its response was lost. Both retry and old pagehide
  // use S1's explicit ID after another tab with the same cookie creates S2.
  for (const oldPath of ["cleanup retry", "pagehide"])
    assert.equal(
      (await post("/api/end", { session_id: firstSession.id }, cookie)).status,
      200,
      oldPath,
    );
  assert.equal((await post("/api/session", {}, cookie)).status, 409);
  assert.equal(
    (await post("/api/end", { session_id: secondSession.id }, cookie)).status,
    200,
  );
});
