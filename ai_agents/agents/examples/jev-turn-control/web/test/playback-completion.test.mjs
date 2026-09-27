import test from "node:test";
import assert from "node:assert/strict";
import { Player } from "../public/audio.js";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
class Context {
  currentTime = 0;
  outputLatency = 0.24;
  destination = {};
  nodes = [];
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

test("incoming audio crosses the buffer budget once, preserving cause", async (t) => {
  const { p, reports } = await fixture(t);
  p.ctx.outputLatency = 0;
  for (let i = 0; i < 299; i++) assert.ok(p.play(frame("r1")));
  assert.equal(p.play(frame("r1", 200)), false);
  const terminal = reports.filter((x) => x.stopped);
  assert.equal(terminal.length, 1);
  assert.equal(terminal[0].reason, "buffer_limit");
  assert.equal(terminal[0].completed, false);
  assert.ok(p.ctx.nodes.every((x) => x.stopped));
  p.stop("r1");
  assert.equal(reports.filter((x) => x.stopped).length, 1);
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
