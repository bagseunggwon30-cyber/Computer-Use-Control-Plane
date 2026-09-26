import assert from "node:assert/strict";
import test from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import cucpExtension, { registerCucpExtension } from "../src/index.ts";
import type { CucpClient } from "../src/client.ts";
import { CucpFailure, type CucpResponse } from "../src/protocol.ts";

function mockPi() {
  const tools: Record<string, any> = {};
  const events: Record<string, any> = {};
  const commands: Record<string, any> = {};
  const pi = {
    registerTool: (tool: any) => { tools[tool.name] = tool; },
    on: (name: string, handler: any) => { events[name] = handler; },
    registerCommand: (name: string, command: any) => { commands[name] = command; },
  } as unknown as ExtensionAPI;
  return { pi, tools, events, commands };
}

test("factory only registers tools, command and lifecycle handlers", async () => {
  const { pi, tools, events, commands } = mockPi();
  cucpExtension(pi);
  assert.deepEqual(Object.keys(tools), ["cucp_windows", "cucp_wait_window", "cucp_observe", "cucp_action", "cucp_batch", "cucp_capabilities", "cucp_privileges"]);
  assert.ok(commands.computer);
  assert.ok(events.session_shutdown);
  for (const tool of Object.values(tools)) assert.equal(tool.executionMode, "sequential");
  await events.session_shutdown();
  await events.session_shutdown();
});

test("Pi execute throws; tool_result hook preserves partial steps/image and isError", async () => {
  const response: CucpResponse = {
    schema: "cucp.response/v1", id: "engine-id", command: "batch", status: "partial", duration_ms: 1,
    errors: [{ code: "FOCUS_LOST", message: "Target is no longer foreground" }],
    data: { steps: [{ command: "click", status: "ok" }, { command: "type", status: "error" }], image: { mime_type: "image/png", data: "AAAA", width: 1, height: 1 } },
  };
  const client = { request: async () => { throw new CucpFailure(response); }, dispose: async () => {} } as unknown as CucpClient;
  const { pi, tools, events } = mockPi();
  registerCucpExtension(pi, client);
  await assert.rejects(tools.cucp_batch.execute("tool-1", { actions: [] }), /FOCUS_LOST/);
  const transformed = events.tool_result({ toolCallId: "tool-1", toolName: "cucp_batch", isError: true });
  assert.equal(transformed.isError, true);
  assert.equal(transformed.details.data.steps.length, 2);
  assert.equal(transformed.content[1].type, "image");
  assert.equal(events.tool_result({ toolCallId: "tool-1", toolName: "cucp_batch" }), undefined);
});

test("human command toggles mode; model tools only forward declared operations", async () => {
  const calls: unknown[] = [];
  const client = {
    liveControl: false,
    setLiveControl: async (enabled: boolean) => { calls.push(enabled); },
    request: async (command: string, args: unknown) => {
      calls.push({ command, args });
      return { schema: "cucp.response/v1", id: "1", command, status: "ok", data: {}, errors: [], duration_ms: 1 };
    },
  } as unknown as CucpClient;
  const { pi, tools, commands } = mockPi();
  registerCucpExtension(pi, client);
  const ctx = { ui: { notify: () => {} } };
  await commands.computer.handler("on", ctx);
  await tools.cucp_action.execute("tool-1", { command: "type", args: { observation_id: "snapshot", text: "한글 입력" } });
  await commands.computer.handler("off", ctx);
  assert.deepEqual(calls, [true, { command: "type", args: { observation_id: "snapshot", text: "한글 입력" } }, false]);
});
