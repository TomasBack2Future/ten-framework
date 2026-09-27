import test from "node:test";
import assert from "node:assert/strict";
import { Player } from "../public/audio.js";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
class Context {
  currentTime = 0;
  outputLatency = 0.24;
  destination = {};
  nodes = [];
  createGain() {
    return { gain: { value: 1 }, connect() {} };
  }
  async resume() {}
  async close() {}
  createBuffer(_channels, n, rate) {
    return { duration: n / rate, getChannelData: () => new Float32Array(n) };
  }
  createBufferSource() {
    const node = {
      connect() {},
      disconnect() {},
      start() {},
      stop() {
        this.stopped = true;
        this.onended?.();
      },
    };
    this.nodes.push(node);
    return node;
  }
}
function frame(id, ms = 100) {
  return {
    audio: Buffer.alloc(ms * 32).toString("base64"),
    metadata: {
      response_id: id,
      sample_rate: 16000,
      channels: 1,
      bytes_per_sample: 2,
    },
  };
}
async function fixture(t) {
  const reports = [],
    p = new Player((x) => reports.push(x), Context);
  await p.unlock();
  t.after(() => p.destroy());
  p.begin("r1");
  return { p, reports };
}

test("natural completion waits for the compensated cursor, without inventing heard text", async (t) => {
  const { p, reports } = await fixture(t);
  p.play(frame("r1", 1000));
  p.audioComplete("r1");
  p.ctx.currentTime = 1.015;
  p.ctx.nodes[0].onended();
  // The previous fixed150ms drain with240ms output latency reported910/1000ms.
  p.ctx.currentTime = 1.165;
  await sleep(175);
  assert.equal(
    reports.some((x) => x.completed),
    false,
  );
  assert.equal(p.cursor(), 910);
  p.ctx.currentTime = 1.255;
  await sleep(190);
  const terminal = reports.filter((x) => x.completed);
  assert.equal(terminal.length, 1);
  assert.equal(terminal[0].played_ms, 1000);
  assert.equal(terminal[0].accuracy, "estimated");
});

test("stop during latency drain stays partial and cannot become completed", async (t) => {
  const { p, reports } = await fixture(t);
  p.play(frame("r1", 1000));
  p.audioComplete("r1");
  p.ctx.currentTime = 1.015;
  p.ctx.nodes[0].onended();
  p.ctx.currentTime = 1.1;
  p.stop("r1");
  p.stop("r1");
  p.ctx.currentTime = 2;
  await sleep(300);
  const terminal = reports.filter((x) => x.stopped || x.completed);
  assert.equal(terminal.length, 1);
  assert.equal(terminal[0].stopped, true);
  assert.equal(terminal[0].played_ms, 845);
  assert.equal(terminal[0].completed, false);
});

test("audio beyond 30 seconds stays queued until explicitly stopped", async (t) => {
  const { p, reports } = await fixture(t);
  p.ctx.outputLatency = 0;
  for (let i = 0; i < 400; i++) assert.ok(p.play(frame("r1")));
  assert.ok(p.next - p.ctx.currentTime > 40);
  assert.equal(p.response, "r1");
  assert.equal(reports.filter((x) => x.stopped || x.completed).length, 0);
  assert.ok(p.ctx.nodes.every((x) => !x.stopped));
  p.stop("r1");
  assert.ok(p.ctx.nodes.every((x) => x.stopped));
  assert.equal(reports.filter((x) => x.stopped).length, 1);
  assert.equal(p.play(frame("r1")), false);
  p.begin("r2");
  assert.ok(p.play(frame("r2")));
  assert.equal(p.play(frame("r1")), false);
});

test("late old onended cannot finish a newer response", async (t) => {
  const { p, reports } = await fixture(t);
  p.play(frame("r1"));
  const old = p.ctx.nodes[0];
  p.stop("r1");
  p.begin("r2");
  p.play(frame("r2"));
  p.audioComplete("r2");
  old.onended();
  await sleep(200);
  assert.equal(
    reports.some((x) => x.response_id === "r2" && x.completed),
    false,
  );
});

test("speaker mute preserves only audible prefix; unmute starts at next reply", async (t) => {
  const { p, reports } = await fixture(t);
  p.ctx.outputLatency = 0;
  p.play(frame("r1", 1000));
  p.ctx.currentTime = 0.415;
  p.setMuted(true);
  assert.equal(p.gain.gain.value, 0);
  assert.equal(p.cursor(), 400);
  p.setMuted(false);
  assert.equal(p.gain.gain.value, 0);
  p.ctx.currentTime = 1.1;
  p.audioComplete("r1");
  p.ctx.nodes[0].onended();
  await sleep(180);
  const end = reports.find((x) => x.reason === "muted");
  assert.equal(end.played_ms, 400);
  assert.equal(end.completed, false);
  assert.equal(end.stopped, true);
  p.begin("r2");
  assert.equal(p.gain.gain.value, 1);
  assert.ok(p.play(frame("r2")));
  p.setMuted(true);
  p.begin("r3");
  assert.equal(p.cursor(), 0);
  assert.equal(p.gain.gain.value, 0);
});
