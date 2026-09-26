import { createInterface } from "node:readline";
import { appendFileSync } from "node:fs";

export const png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a+6sAAAAASUVORK5CYII=";
let count = 0;
createInterface({ input: process.stdin }).on("line", async line => {
  const request = JSON.parse(line);
  if (process.env.CUCP_TEST_LOG) appendFileSync(process.env.CUCP_TEST_LOG, request.command + "\n");
  const response = {
    schema: "cucp.response/v1", id: request.id, command: request.command,
    status: "ok", data: { args: request.args, count: ++count }, errors: [], duration_ms: 1,
  };
  if (request.command === "hang") return;
  if (request.command === "exit") process.exit(7);
  if (request.command === "malformed") { process.stdout.write("not JSON\n"); return; }
  if (request.command === "flood") { process.stdout.write("X".repeat(4096)); return; }
  if (request.command === "mismatch") response.id = "different-request";
  if (request.command === "delay") await new Promise(r => setTimeout(r, 40));
  if (request.command === "capabilities") {
    response.data.live = process.argv.includes("--allow-live-control");
    response.data.pythonpath = process.env.PYTHONPATH;
  }
  if (["observe", "fail"].includes(request.command)) {
    response.data.image = { mime_type: "image/png", data: png, width: 1, height: 1 };
    response.data.observation_id = "observed-" + count;
  }
  if (request.command === "fail") {
    response.status = "partial";
    response.data.steps = [{ command: "click", status: "ok" }, { command: "type", status: "error" }, { command: "key", status: "skipped" }];
    response.errors = [{ code: "FOCUS_LOST", message: "Focus changed" }];
  }
  process.stdout.write(JSON.stringify(response) + "\n");
});
