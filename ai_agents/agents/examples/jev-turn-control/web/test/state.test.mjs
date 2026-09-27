import test from "node:test";
import assert from "node:assert/strict";
import { EventStore } from "../public/state.js";
import { Player } from "../public/audio.js";
const event = (seq, type = "decision.completed", session_id = "a") => ({
  seq,
  type,
  session_id,
  payload: { phase: "listening" },
});
test("duplicates and stale sessions cannot change state; snapshot restores with bounded retention", () => {
  const s = new EventStore(3);
  assert.ok(s.apply(event(1)));
  assert.equal(s.apply(event(1)), false);
  for (let i = 2; i <= 10; i++) s.apply(event(i));
  assert.equal(s.events.length, 3);
  assert.equal(s.apply(event(11, "response.started", "b")), false);
  assert.ok(s.apply(event(1, "state.snapshot", "b")));
  assert.equal(s.state.phase, "listening");
  assert.equal(s.events.length, 1);
});
test("cancel stops active and queued sources; late audio cannot restart old response", async () => {
  const nodes = [];
  class Context {
    currentTime = 0;
    destination = {};
    state = "running";
    async resume() {}
    async close() {}
    createBuffer(c, n, r) {
      return { duration: n / r, getChannelData: () => new Float32Array(n) };
    }
    createBufferSource() {
      const n = {
        connect() {},
        disconnect() {},
        start() {},
        stop() {
          this.stopped = true;
        },
      };
      nodes.push(n);
      return n;
    }
  }
  const reports = [];
  const p = new Player((x) => reports.push(x), Context);
  await p.unlock();
  p.begin("r1");
  const m = {
    audio: btoa("\0".repeat(3200)),
    metadata: {
      response_id: "r1",
      sample_rate: 16000,
      channels: 1,
      bytes_per_sample: 2,
    },
  };
  assert.ok(p.play(m));
  assert.ok(p.play(m));
  p.ctx.currentTime = 0.06;
  p.stop("r1");
  assert.ok(nodes.every((n) => n.stopped));
  assert.equal(reports.at(-1).stopped, true);
  assert.equal(reports.at(-1).accuracy, "estimated");
  assert.equal(p.play(m), false);
  p.begin("r1");
  assert.equal(p.play(m), false);
  p.begin("r2");
  assert.equal(p.play(m), false);
  await p.destroy();
});
