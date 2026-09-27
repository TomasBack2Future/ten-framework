/** Run inside the credential-free runtime image; checks actual TEN graph I/O. */
import { spawn } from "node:child_process";
import { once } from "node:events";
import assert from "node:assert/strict";
import { WebSocket } from "ws";
const child = spawn(process.execPath, ["web/server.mjs"], {
  env: {
    ...process.env,
    JEV_ALLOW_LOCAL: "1",
    JEV_ACCESS_CODE: "",
    JEV_MODE: "mock",
    PORT: "3309",
    JEV_PUBLIC_ORIGIN: "http://localhost:3309",
  },
  stdio: ["ignore", "pipe", "inherit"],
});
let ws, session;
try {
  await once(child.stdout, "data");
  const start = await fetch("http://localhost:3309/api/session", {
    method: "POST",
    headers: {
      Origin: "http://localhost:3309",
      "Content-Type": "application/json",
    },
    body: "{}",
  });
  assert.equal(start.status, 200);
  session = await start.json();
  ws = new WebSocket("ws://localhost:3309/ws", {
    headers: { Origin: "http://localhost:3309" },
  });
  const events = [];
  let audio = 0;
  let response;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(Error(`TEN graph timeout; observed ${events.join(",")}`)),
      20000,
    );
    ws.on("error", reject);
    ws.on("message", (raw) => {
      const m = JSON.parse(raw);
      if (m.type === "audio") {
        audio++;
        return;
      }
      if (m.name !== "jev_event") return;
      const e = m.data;
      events.push(e.type);
      if (e.type === "state.snapshot")
        ws.send(
          JSON.stringify({
            type: "data",
            name: "jev_asr",
            data: {
              text: "What is the weather?",
              final: true,
              segment_id: "test-one",
            },
          }),
        );
      if (e.type === "response.started") {
        response = e.response_id;
        setTimeout(
          () =>
            ws.send(
              JSON.stringify({
                type: "data",
                name: "jev_control",
                data: { action: "stop" },
              }),
            ),
          200,
        );
      }
      if (e.type === "response.cancelled") {
        ws.send(
          JSON.stringify({
            type: "data",
            name: "jev_playback",
            data: {
              response_id: response,
              played_ms: 100,
              stopped: true,
              completed: false,
              accuracy: "estimated",
            },
          }),
        );
      }
      if (e.type === "playback.stopped") {
        clearTimeout(timer);
        resolve();
      }
    });
  });
  assert.ok(audio > 0, "Native mock graph must emit PCM audio");
  assert.ok(events.includes("decision.completed"));
  assert.ok(events.includes("response.cancelled"));
  console.log(
    "JEV_NATIVE_WS_SMOKE_PASS",
    JSON.stringify({ audio_frames: audio, events }),
  );
} finally {
  ws?.close();
  if (session)
    await fetch("http://localhost:3309/api/end", {
      method: "POST",
      headers: {
        Origin: "http://localhost:3309",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ session_id: session.id }),
    }).catch(() => {});
  child.kill("SIGTERM");
}
