import test from "node:test";
import assert from "node:assert/strict";

for (const failure of ["unlock", "busy", "initialize", "cleanup"]) {
  test(`Connect recovers from ${failure} and retries`, async (t) => {
    const originals = new Map();
    const replace = (name, value) => {
      originals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
      Object.defineProperty(globalThis, name, {
        configurable: true,
        writable: true,
        value,
      });
    };
    t.after(() => {
      for (const [name, descriptor] of originals)
        if (descriptor) Object.defineProperty(globalThis, name, descriptor);
        else delete globalThis[name];
    });
    const elements = new Map();
    const get = (id) => {
      if (!elements.has(id))
        elements.set(id, {
          disabled: false,
          checked: false,
          value: "",
          textContent: "",
          hidden: false,
          dataset: {},
          setAttribute() {},
          querySelector() {
            return { textContent: "" };
          },
          replaceChildren() {},
        });
      return elements.get(id);
    };
    let broken = true,
      closed = 0;
    const requests = [];
    replace("document", {
      getElementById: get,
      createElement: () => ({ textContent: "" }),
    });
    const listeners = {};
    replace("window", {
      addEventListener(name, fn) {
        listeners[name] = fn;
      },
    });
    const beacons = [];
    replace("navigator", {
      sendBeacon(path, body) {
        beacons.push({ path, body });
      },
    });
    replace("location", { protocol: "https:", host: "demo.test" });
    replace("setInterval", () => 123);
    replace("clearInterval", () => {});
    replace(
      "AudioContext",
      class {
        createGain() {
          return { gain: { value: 1 }, connect() {} };
        }
        async resume() {
          if (broken && failure === "unlock") throw new Error("unlock failed");
        }
        async close() {
          closed++;
        }
      },
    );
    replace(
      "WebSocket",
      class {
        static OPEN = 1;
        constructor() {
          if (broken && ["initialize", "cleanup"].includes(failure))
            throw new Error("initialization failed");
        }
        close() {}
      },
    );
    replace("fetch", async (path, options) => {
      const body = options ? JSON.parse(options.body) : null;
      requests.push({ path, body });
      const error =
        broken &&
        ((failure === "busy" && path === "/api/session") ||
          (failure === "cleanup" && path === "/api/end"));
      return {
        ok: !error,
        status: error ? 409 : 200,
        json: async () =>
          error
            ? { error: "busy or cleanup failed" }
            : path === "/api/config"
              ? { mode: "mock", revision: "test", authenticated: true }
              : { id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", expires_at: null },
      };
    });
    await import(`../public/app.js?failure=${failure}`);
    await new Promise((resolve) => setImmediate(resolve));
    await get("connect").onclick();
    assert.equal(get("connect").disabled, false);
    assert.equal(get("voice-prompt").disabled, false);
    assert.equal(get("mic").disabled, true);
    assert.equal(closed, 1);
    const cleanup = requests.filter((x) => x.path === "/api/end");
    assert.equal(
      cleanup.length,
      ["initialize", "cleanup"].includes(failure) ? 1 : 0,
    );
    if (cleanup.length)
      assert.deepEqual(cleanup[0].body, {
        session_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      });
    if (failure === "unlock")
      assert.equal(
        requests.some((x) => x.path === "/api/session"),
        false,
      );
    if (failure === "cleanup") assert.equal(get("end").disabled, false);
    broken = false;
    const retryStart = requests.length;
    await get("connect").onclick();
    assert.equal(get("connect").disabled, true);
    assert.equal(get("voice-prompt").disabled, true);
    if (failure === "cleanup")
      assert.equal(requests[retryStart].path, "/api/end");
    listeners.pagehide();
    assert.deepEqual(JSON.parse(await beacons[0].body.text()), {
      session_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    });
    await get("end").onclick();
    assert.deepEqual(requests.at(-1).body, {
      session_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    });
    listeners.pagehide();
    assert.equal(beacons.length, 1);
  });
}
