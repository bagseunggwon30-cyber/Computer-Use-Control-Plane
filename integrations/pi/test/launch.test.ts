import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { engineLaunch } from "../src/launch.ts";

function fixture(t: { after: (fn: () => void) => void }) {
  const root = mkdtempSync(join(tmpdir(), "CUCP 한글 "));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return root;
}
const env = { CUCP_EXECUTABLE: "", CUCP_PYTHON: "source-python", PYTHONPATH: "old-path" };

test("portable discovery selects the sibling executable without Python arguments", t => {
  const root = fixture(t);
  writeFileSync(join(root, "CUCP.exe"), "");
  const launch = engineLaunch({ root, env }, false);
  assert.equal(launch.executable, join(root, "CUCP.exe"));
  assert.deepEqual(launch.argv, ["serve"]);
  assert.equal(launch.env.PYTHONPATH, undefined);
  assert.deepEqual(engineLaunch({ root, env }, true).argv, ["serve", "--allow-live-control"]);
});

test("explicit external bundle wins; spaces are a single argv executable", t => {
  const root = fixture(t);
  const exe = join(root, "다른 CUCP.exe");
  writeFileSync(exe, "");
  const launch = engineLaunch({ root, env: { ...env, CUCP_EXECUTABLE: exe } }, false);
  assert.equal(launch.executable, exe);
  assert.deepEqual(launch.argv, ["serve"]);
});

test("broken explicit bundle never falls back to an existing sibling", t => {
  const root = fixture(t);
  writeFileSync(join(root, "CUCP.exe"), "");
  assert.throws(() => engineLaunch({ root, env: { ...env, CUCP_EXECUTABLE: join(root, "missing.exe") } }, false), /not found/);
  for (const path of ["relative.exe", join(root, "wrapper.cmd"), join(root, "wrapper.ps1")]) {
    assert.throws(() => engineLaunch({ root, env: { ...env, CUCP_EXECUTABLE: path } }, false), /absolute executable/);
  }
});

test("source checkout remains supported with explicit Python", t => {
  const root = fixture(t);
  const source = join(root, "pcucp-next", "python", "pcucp_cli");
  mkdirSync(source, { recursive: true });
  writeFileSync(join(source, "__main__.py"), "");
  const launch = engineLaunch({ root, env }, false);
  assert.equal(launch.executable, "source-python");
  assert.deepEqual(launch.argv, ["-u", "-m", "pcucp_cli", "serve"]);
  assert.match(launch.env.PYTHONPATH!, /pcucp-next/);
});

test("detached adapter without engine fails with setup guidance", t => {
  const root = fixture(t);
  assert.throws(() => engineLaunch({ root, env }, false), /CUCP_EXECUTABLE/);
});
