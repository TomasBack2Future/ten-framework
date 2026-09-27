import test from "node:test";
import assert from "node:assert/strict";
import { RTCConnection } from "../public/rtc.js";

function setup() {
  const calls = [],
    handlers = {},
    errors = [];
  const local = {
    setEnabled: async (on) => calls.push(["mic", on]),
    stop: () => calls.push(["local-stop"]),
    close: () => calls.push(["local-close"]),
  };
  const remote = {
    play: () => calls.push(["play"]),
    stop: () => calls.push(["remote-stop"]),
  };
  const client = {
    on: (event, handler) => {
      handlers[event] = handler;
    },
    setClientRole: async (role) => calls.push(["role", role]),
    join: async (...args) => {
      assert.ok(handlers["user-published"]);
      calls.push(["join", ...args]);
    },
    publish: async (tracks) => calls.push(["publish", tracks]),
    subscribe: async (...args) => calls.push(["subscribe", ...args]),
    renewToken: async (token) => calls.push(["renew", token]),
    leave: async () => calls.push(["leave"]),
  };
  const sdk = {
    createClient: (config) => {
      assert.equal(config.mode, "live");
      return client;
    },
    createMicrophoneAudioTrack: async () => local,
  };
  const rtc = new RTCConnection(sdk, {
    token: async () => ({ token: "new" }),
    error: (e) => errors.push(e),
  });
  return { rtc, sdk, calls, handlers, client, local, remote, errors };
}
const credentials = {
  app_id: "app",
  channel: "channel",
  token: "token",
  uid: 1001,
  bot_uid: 1002,
};

test("joins matching identity, filters remote UID, publishes mic and renews token", async () => {
  const s = setup();
  await s.rtc.prepare();
  await s.rtc.join(credentials);
  assert.deepEqual(
    s.calls.find((c) => c[0] === "join"),
    ["join", "app", "channel", "token", 1001],
  );
  await s.handlers["user-published"](
    { uid: 999, audioTrack: s.remote },
    "audio",
  );
  assert.equal(s.calls.filter((c) => c[0] === "play").length, 0);
  await s.handlers["user-published"](
    { uid: 1002, audioTrack: s.remote },
    "audio",
  );
  assert.equal(s.calls.filter((c) => c[0] === "play").length, 1);
  await s.handlers["token-privilege-will-expire"]();
  await s.handlers["token-privilege-did-expire"]();
  assert.equal(
    s.calls.filter((c) => c[0] === "renew" && c[1] === "new").length,
    2,
  );
});

test("unpublish ends old track; next publish resumes; output mute waits for next reply", async () => {
  const s = setup(),
    user = { uid: 1002, audioTrack: null };
  user.audioTrack = s.remote;
  await s.rtc.prepare();
  await s.rtc.join(credentials);
  await s.handlers["user-published"](user, "audio");
  s.rtc.stop();
  await s.handlers["user-unpublished"](user, "audio");
  await s.handlers["user-published"](user, "audio");
  assert.equal(s.calls.filter((c) => c[0] === "play").length, 1);
  s.rtc.begin();
  assert.equal(s.calls.filter((c) => c[0] === "play").length, 2);
  s.rtc.setMuted(true);
  s.rtc.setMuted(false);
  assert.equal(s.calls.filter((c) => c[0] === "play").length, 2);
  s.rtc.begin();
  assert.equal(s.calls.filter((c) => c[0] === "play").length, 3);
});

test("cleanup stops/closes microphone before leaving and ignores late callbacks", async () => {
  const s = setup();
  await s.rtc.prepare();
  await s.rtc.join(credentials);
  await s.rtc.destroy();
  assert.deepEqual(s.calls.slice(-3), [
    ["local-stop"],
    ["local-close"],
    ["leave"],
  ]);
  await s.handlers["user-published"](
    { uid: 1002, audioTrack: s.remote },
    "audio",
  );
  assert.equal(s.calls.filter((c) => c[0] === "play").length, 0);
});

test("join failure releases tracks instead of leaving partial initialization", async () => {
  const s = setup();
  s.client.join = async () => {
    throw Error("join failed");
  };
  await s.rtc.prepare();
  await assert.rejects(s.rtc.join(credentials), /join failed/);
  assert.equal(s.rtc.local, null);
  assert.equal(s.rtc.client, null);
  assert.deepEqual(s.calls.slice(-3), [
    ["local-stop"],
    ["local-close"],
    ["leave"],
  ]);
});

test("late subscribe after unpublish does not replay an obsolete track", async () => {
  const s = setup();
  let release;
  s.client.subscribe = () =>
    new Promise((r) => {
      release = r;
    });
  await s.rtc.prepare();
  await s.rtc.join(credentials);
  const user = { uid: 1002, audioTrack: s.remote };
  const pending = s.handlers["user-published"](user, "audio");
  await new Promise((r) => setImmediate(r));
  await s.handlers["user-unpublished"](user, "audio");
  release();
  await pending;
  assert.equal(s.calls.filter((c) => c[0] === "play").length, 0);
});
