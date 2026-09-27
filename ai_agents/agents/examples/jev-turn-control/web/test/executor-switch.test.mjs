import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import net from "node:net";

for (const enabled of ["false", "true"]) {
  test(`operator gate ${enabled}: advertises capability and rejects forbidden overrides`, async (t) => {
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
        JEV_MODE: "live",
        JEV_CODEX_ENABLED: enabled,
        JEV_GRAPH_COMMAND: "",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    t.after(() => child.kill("SIGTERM"));
    await once(child.stdout, "data");
    const config = await (await fetch(origin + "/api/config")).json();
    assert.equal(config.executor_available, enabled === "true");
    const post = (route, data, cookie) =>
      fetch(origin + route, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: origin,
          ...(cookie ? { Cookie: cookie } : {}),
        },
        body: JSON.stringify(data),
      });
    const login = await post("/api/login", { code: "test-only-secret" });
    const cookie = login.headers.get("set-cookie").split(";")[0];
    assert.equal(
      (
        await post(
          "/api/session",
          { settings: { "executor.url": "http://bad" } },
          cookie,
        )
      ).status,
      400,
    );
    // With the gate enabled, validation passes but missing voice graph fails (503).
    assert.equal(
      (
        await post(
          "/api/session",
          { settings: { "executor.enabled": true } },
          cookie,
        )
      ).status,
      enabled === "true" ? 503 : 400,
    );
  });
}
