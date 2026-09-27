import { mkdirSync, createWriteStream, openSync } from "node:fs";
import path from "node:path";
import { finished } from "node:stream/promises";

const credential =
  /api[_-]?key|authorization|cookie|password|secret|access[_-]?token|refresh[_-]?token|access[_-]?code|^token$|[_-]token$|[_-]key$|certificate/i;
export function redact(value) {
  if (typeof value === "string") {
    for (const [name, secret] of Object.entries(process.env))
      if (credential.test(name) && secret)
        value = value.split(secret).join("[credential]");
    return value.replace(
      /Bearer\s+[A-Za-z0-9._~+/=-]+/gi,
      "Bearer [credential]",
    );
  }
  if (Array.isArray(value)) return value.map(redact);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value).map(([k, v]) => [
      k,
      credential.test(k) ? "[credential]" : redact(v),
    ]),
  );
}
export function observer(sessionId, revision) {
  const root = process.env.JEV_EVENT_LOG_DIR;
  if (!root)
    return {
      write() {},
      audio() {},
      close() {
        return Promise.resolve();
      },
    };
  if (!/^[a-zA-Z0-9_-]+$/.test(sessionId))
    throw Error("Invalid evidence session id");
  const directory = path.join(root, sessionId);
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const streams = new Map(),
    offsets = new Map();
  let sequence = 0,
    closed = false,
    failure;
  function stream(name) {
    if (!streams.has(name)) {
      const output = createWriteStream(path.join(directory, name), {
        fd: openSync(path.join(directory, name), "ax", 0o600),
        autoClose: true,
      });
      output.on("error", () => {
        failure = Error("Evidence storage failed");
        console.error("JEV_EVIDENCE_WRITE_FAILED");
      });
      streams.set(name, output);
    }
    return streams.get(name);
  }
  function append(name, data) {
    if (failure) return false;
    if (closed) throw Error("Evidence session closed");
    let output;
    try {
      output = stream(name);
    } catch {
      console.error("JEV_EVIDENCE_OPEN_FAILED");
      failure = Error("Evidence storage unavailable");
      return false;
    }
    if (output.writableLength > 64 * 1024 * 1024) {
      console.error("JEV_EVIDENCE_QUEUE_FULL");
      failure = Error("Evidence storage stalled");
      return false;
    }
    output.write(data);
    return true;
  }
  const write = (event) => {
    append(
      "web.jsonl",
      JSON.stringify({
        schema: "jev.evidence.v1",
        source: "web",
        record_seq: ++sequence,
        session_id: sessionId,
        revision,
        wall_time_ms: Date.now(),
        monotonic_ns: process.hrtime.bigint().toString(),
        event: redact(event),
      }) + "\n",
    );
  };
  return {
    write,
    audio(direction, encoded, metadata) {
      const name = direction === "input" ? "user.pcm" : "delivered.pcm";
      const pcm = Buffer.from(encoded, "base64"),
        offset = offsets.get(name) || 0;
      if (!append(name, pcm)) return;
      offsets.set(name, offset + pcm.length);
      write({
        type: `audio.${direction}`,
        response_id: metadata?.response_id,
        payload: { file: name, offset, length: pcm.length, metadata },
      });
    },
    async close() {
      if (closed) return;
      closed = true;
      const pending = [...streams.values()].map((output) => {
        const done = finished(output);
        output.end();
        return done;
      });
      await Promise.all(pending);
      if (failure) throw failure;
    },
  };
}
