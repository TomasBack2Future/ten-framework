import {
  mkdirSync,
  readdirSync,
  unlinkSync,
  createWriteStream,
  openSync,
} from "node:fs";
import path from "node:path";
const textKeys = new Set([
  "text",
  "heard_text",
  "input_text",
  "context",
  "heard_context",
  "context_summary",
  "summary",
  "phrase",
  "prompt",
]);
export function redact(value, includeText = false, depth = 0) {
  if (depth > 8) return "[bounded]";
  if (typeof value === "string") return value.slice(0, 24000);
  if (Array.isArray(value))
    return value.slice(0, 128).map((x) => redact(x, includeText, depth + 1));
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value)
      .slice(0, 80)
      .map(([k, v]) => [
        k,
        /key|token|cookie|authorization|secret/i.test(k) ||
        (!includeText && textKeys.has(k))
          ? "[redacted]"
          : redact(v, includeText, depth + 1),
      ]),
  );
}
export function observer(sessionId, revision) {
  const directory = process.env.JEV_EVENT_LOG_DIR;
  if (!directory) return { write() {}, close() {} };
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const files = readdirSync(directory)
    .filter((x) => /^jev-\d+-[a-f0-9]+\.jsonl$/.test(x))
    .sort();
  for (const file of files.slice(0, Math.max(0, files.length - 9)))
    unlinkSync(path.join(directory, file));
  const filename = path.join(directory, `jev-${Date.now()}-${sessionId}.jsonl`);
  const stream = createWriteStream(filename, {
    fd: openSync(filename, "wx", 0o600),
    autoClose: true,
  });
  let bytes = 0,
    disabled = false;
  stream.on("error", () => {
    disabled = true;
  });
  return {
    write(event) {
      if (disabled) return;
      const line =
        JSON.stringify({
          revision,
          session_id: sessionId,
          recorded_at: new Date().toISOString(),
          ...redact(event, process.env.JEV_EVENT_LOG_TEXT === "1"),
        }) + "\n";
      bytes += Buffer.byteLength(line);
      if (bytes > 2 * 1024 * 1024 || stream.writableLength > 65536) {
        disabled = true;
        stream.end(
          JSON.stringify({
            type: "observation.limit",
            revision,
            session_id: sessionId,
          }) + "\n",
        );
        return;
      }
      stream.write(line);
    },
    close() {
      stream.end();
    },
  };
}
