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
  assert.equal(
    (
      await post(
        "/api/session",
        { settings: { "start.enabled": true } },
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
  assert.equal((await post("/api/end", {}, cookie)).status, 200);
  assert.equal((await post("/api/session", {}, cookie)).status, 200);
  await post("/api/end", {}, cookie);
});
