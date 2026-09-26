/** Actual Python transport/contract check; no native OS input is issued. */
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { CucpClient } from "../src/client.ts";
import { CucpFailure } from "../src/protocol.ts";

const client = new CucpClient({ root: fileURLToPath(new URL("../../..", import.meta.url)) });
try {
  const capabilities = await client.request("capabilities", {});
  assert.equal(capabilities.data.allow_live_control, false);
  assert.ok((capabilities.data.commands as { name: string }[]).some(command => command.name === "observe"));
  await assert.rejects(client.request("click", { observation_id: "nonexistent", x: 1, y: 1 }), error => {
    assert.ok(error instanceof CucpFailure);
    assert.equal(error.response.status, "blocked");
    assert.equal(error.response.errors[0].code, "live_control_required");
    return true;
  });
  await assert.rejects(client.request("not-a-command", {}), error => {
    assert.ok(error instanceof CucpFailure);
    assert.equal(error.response.errors[0].code, "unknown_command");
    return true;
  });
  await client.setLiveControl(true);
  assert.equal((await client.request("capabilities", {})).data.allow_live_control, true);
  await assert.rejects(client.request("type", { observation_id: "nonexistent", text: "must never execute" }), error => {
    assert.ok(error instanceof CucpFailure);
    assert.equal(error.response.errors[0].code, "stale_observation");
    return true;
  });
  await client.setLiveControl(false);
  assert.equal((await client.request("capabilities", {})).data.allow_live_control, false);
  console.log("Actual Python engine integration passed: capabilities, read-only denial, unknown command, mode restart, stale observation denial.");
} finally { await client.dispose(); }
