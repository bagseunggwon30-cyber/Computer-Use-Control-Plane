import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { CucpClient, type ClientOptions } from "../src/client.ts";
import { CucpFailure, parseResponse, toToolResult } from "../src/protocol.ts";

const fixture = fileURLToPath(new URL("fake-engine.mjs", import.meta.url));
const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const make = (overrides: Partial<ClientOptions> = {}) => new CucpClient({ root, executable: process.execPath, argv: [fixture], timeoutMs: 2000, ...overrides });

test("client is lazy; requests reuse one process and serialize observations/actions", async () => {
  const client = make();
  try {
    assert.equal(client.running, false);
    const [a, b] = await Promise.all([client.request("delay", {}), client.request("observe", {})]);
    assert.equal(a.data.count, 1);
    assert.equal(b.data.count, 2);
    assert.equal(client.running, true);
  } finally { await client.dispose(); }
});

test("actual image content, metadata preserved, no base64 duplicated into text/details", async () => {
  const client = make();
  try {
    const result = toToolResult(await client.request("observe", {}));
    assert.equal(result.content[1].type, "image");
    assert.equal(result.content[0].type, "text");
    const serialized = JSON.stringify(result.details);
    assert.match(serialized, /delivered_as/);
    assert.doesNotMatch(serialized, /iVBOR/);
  } finally { await client.dispose(); }
});

test("partial/error throws and retains steps, errors and useful image", async () => {
  const client = make();
  try {
    await assert.rejects(client.request("fail", {}), error => {
      assert.ok(error instanceof CucpFailure);
      assert.equal(error.response.status, "partial");
      assert.equal((error.response.data.steps as unknown[]).length, 3);
      assert.equal(toToolResult(error.response).content[1].type, "image");
      return true;
    });
    assert.equal((await client.request("capabilities", {})).data.count, 2);
  } finally { await client.dispose(); }
});

test("live mode defaults off and switching resets the engine", async () => {
  const client = make();
  try {
    assert.equal((await client.request("capabilities", {})).data.live, false);
    await client.setLiveControl(true);
    assert.equal(client.running, false);
    const response = await client.request("capabilities", {});
    assert.equal(response.data.live, true);
    assert.equal(response.data.count, 1);
    assert.match(String(response.data.pythonpath), /pcucp-next/);
    await client.setLiveControl(false);
    assert.equal((await client.request("capabilities", {})).data.live, false);
  } finally { await client.dispose(); }
});

test("abort kills transport, cancels queued action, never replays, then permits a fresh observation", async () => {
  const folder = await mkdtemp(resolve(tmpdir(), "cucp-pi-test-"));
  const log = resolve(folder, "commands.log");
  const client = make({ env: { CUCP_TEST_LOG: log } });
  try {
    await client.request("capabilities", {});
    const controller = new AbortController();
    const hanging = assert.rejects(client.request("hang", {}, controller.signal), /cancelled/);
    const queued = assert.rejects(client.request("click", { observation_id: "old" }), /queued operation cancelled/);
    await new Promise(r => setTimeout(r, 40));
    controller.abort();
    await Promise.all([hanging, queued]);
    assert.equal(client.running, false);
    await client.request("observe", {});
    const commands = (await readFile(log, "utf8")).trim().split("\n");
    assert.deepEqual(commands, ["capabilities", "hang", "observe"]);
  } finally { await client.dispose(); await rm(folder, { recursive: true, force: true }); }
});

test("queued pre-aborted request does not stop the active operation", async () => {
  const client = make();
  try {
    const controller = new AbortController();
    const active = client.request("delay", {});
    const queued = assert.rejects(client.request("click", {}, controller.signal), /cancelled before execution/);
    controller.abort();
    await active; await queued;
    assert.equal((await client.request("capabilities", {})).data.count, 2);
  } finally { await client.dispose(); }
});

for (const [command, message] of [["malformed", /protocol error/], ["mismatch", /mismatched/], ["flood", /byte limit/], ["exit", /engine exited/]] as const) {
  test(`${command} is a real transport failure`, async () => {
    const client = make({ maxResponseBytes: 2048 });
    try {
      await assert.rejects(client.request(command, {}), message);
      assert.equal(client.running, false);
      assert.equal((await client.request("capabilities", {})).data.count, 1);
    } finally { await client.dispose(); }
  });
}

test("timeout invalidates transport; shutdown is idempotent", async () => {
  const client = make({ timeoutMs: 100 });
  await assert.rejects(client.request("hang", {}), /timed out/);
  await Promise.all([client.dispose(), client.dispose()]);
  await assert.rejects(client.request("observe", {}), /closed/);
});

test("invalid envelopes and image payloads are rejected", () => {
  assert.throws(() => parseResponse("{}", "id", "observe"), /invalid/);
  assert.throws(() => toToolResult({ schema: "cucp.response/v1", id: "id", command: "observe", status: "ok", duration_ms: 1, errors: [], data: { image: { mime_type: "text/html", data: "AAAA" } } }), /invalid image/);
});
