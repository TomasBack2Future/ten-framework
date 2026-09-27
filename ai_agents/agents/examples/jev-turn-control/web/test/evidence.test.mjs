import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { observer, redact } from "../observations.mjs";

test("complete long evidence and byte-accurate audio survive UI and old file limits", async (t) => {
  const root = await mkdtemp(`${tmpdir()}/jev-full-evidence-`);
  const old = process.env.JEV_EVENT_LOG_DIR;
  process.env.JEV_EVENT_LOG_DIR = root;
  t.after(async () => {
    if (old === undefined) delete process.env.JEV_EVENT_LOG_DIR;
    else process.env.JEV_EVENT_LOG_DIR = old;
    await rm(root, { recursive: true, force: true });
  });
  await writeFile(`${root}/legacy.jsonl`, "historical evidence");
  const log = observer("session1", "revision1"),
    text = "正文".repeat(14000);
  for (let i = 0; i < 350; i++)
    log.write({
      type: "asr.updated",
      seq: i,
      payload: { text, final: i === 349 },
    });
  log.audio("input", Buffer.from([1, 2, 3, 4]).toString("base64"), {
    sample_rate: 16000,
  });
  log.audio("input", Buffer.from([5, 6]).toString("base64"), {
    sample_rate: 16000,
  });
  log.audio("output", Buffer.from([7, 8]).toString("base64"), {
    response_id: "r1",
  });
  await log.close();
  const rows = (await readFile(`${root}/session1/web.jsonl`, "utf8"))
    .trim()
    .split("\n")
    .map(JSON.parse);
  assert.equal(rows.length, 353);
  assert.equal(rows[349].event.payload.text, text);
  assert.equal(rows[351].event.payload.offset, 4);
  assert.deepEqual(
    [...(await readFile(`${root}/session1/user.pcm`))],
    [1, 2, 3, 4, 5, 6],
  );
  assert.equal(rows[352].event.response_id, "r1");
  assert.ok(
    rows.every(
      (r) => r.revision === "revision1" && r.monotonic_ns && r.wall_time_ms,
    ),
  );
  assert.equal((await stat(`${root}/session1/user.pcm`)).mode & 0o777, 0o600);
  assert.equal(
    await readFile(`${root}/legacy.jsonl`, "utf8"),
    "historical evidence",
  );
});

test("credentials cannot leak through nested fields or business text echoes", () => {
  process.env.GROQ_API_KEY = "test-only-credential-value";
  try {
    const text = JSON.stringify(
      redact({
        messages: [
          { content: "Business text test-only-credential-value remains" },
        ],
        headers: { Authorization: "Bearer abc.def" },
        api_key: "hidden",
        text: "Bearer abc.def",
      }),
    );
    assert.doesNotMatch(text, /test-only-credential-value|abc.def|hidden/);
    assert.match(text, /Business text/);
  } finally {
    delete process.env.GROQ_API_KEY;
  }
});
