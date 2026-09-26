import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomUUID } from "node:crypto";
import { engineLaunch } from "./launch.ts";
import { CucpFailure, parseResponse, type CucpResponse } from "./protocol.ts";

export interface ClientOptions {
  root: string;
  executable?: string;
  /** Test/embedding transport override; not exposed to the model. */
  argv?: string[];
  env?: NodeJS.ProcessEnv;
  timeoutMs?: number;
  maxResponseBytes?: number;
}

interface Pending {
  id: string;
  command: string;
  resolve: (response: CucpResponse) => void;
  reject: (error: Error) => void;
  cleanup: () => void;
}

/** One desktop, one serial stream. A failed transport is never replayed. */
export class CucpClient {
  private child?: ChildProcessWithoutNullStreams;
  private pending?: Pending;
  private buffer = Buffer.alloc(0);
  private stderr = "";
  private queue: Promise<unknown> = Promise.resolve();
  private stopping: Promise<void> = Promise.resolve();
  private epoch = 0;
  private live = false;
  private disposed = false;

  constructor(private readonly options: ClientOptions) {}

  get liveControl(): boolean { return this.live; }
  get running(): boolean { return !!this.child; }

  async setLiveControl(enabled: boolean): Promise<void> {
    if (this.disposed) throw new Error("CUCP client is closed");
    if (this.live === enabled) return;
    this.live = enabled;
    await this.stop(new Error("CUCP mode changed; observe again before acting"));
  }

  async dispose(): Promise<void> {
    if (this.disposed) return this.stopping;
    this.disposed = true;
    await this.stop(new Error("CUCP session closed"));
  }

  request(command: string, args: Record<string, unknown>, signal?: AbortSignal): Promise<CucpResponse> {
    const epoch = this.epoch;
    const work = this.queue.then(async () => {
      if (this.disposed) throw new Error("CUCP client is closed");
      if (signal?.aborted) throw new Error("CUCP operation cancelled before execution");
      if (epoch !== this.epoch) throw new Error("CUCP session changed; queued operation cancelled. Observe again.");
      await this.stopping;
      if (signal?.aborted || epoch !== this.epoch) throw new Error("CUCP operation cancelled before execution");
      this.start();
      return this.exchange(command, args, signal);
    });
    this.queue = work.catch(() => {});
    return work;
  }

  private start(): void {
    if (this.child) return;
    const { executable, argv, env } = engineLaunch(this.options, this.live);
    const child = spawn(executable, argv, {
      cwd: this.options.root,
      env,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      // POSIX uses a process group so abort also kills native descendants.
      detached: process.platform !== "win32",
      shell: false,
    });
    this.child = child;
    this.buffer = Buffer.alloc(0);
    this.stderr = "";
    child.stdout.on("data", (chunk: Buffer) => this.onData(child, chunk));
    child.stderr.on("data", (chunk: Buffer) => {
      if (child === this.child) this.stderr = (this.stderr + chunk.toString("utf8")).slice(-4096);
    });
    child.on("error", error => {
      if (child === this.child) void this.stop(new Error(`CUCP engine could not start: ${error.message}`));
    });
    child.stdin.on("error", error => {
      if (child === this.child) void this.stop(new Error(`CUCP transport failed: ${error.message}`));
    });
    child.on("exit", (code, signal) => {
      if (child !== this.child) return;
      void this.stop(new Error(`CUCP engine exited (${signal ?? code}); action outcome may be unknown. Observe again. ${this.stderr}`));
    });
  }

  private exchange(command: string, args: Record<string, unknown>, signal?: AbortSignal): Promise<CucpResponse> {
    return new Promise((resolveRequest, reject) => {
      const id = randomUUID();
      const cancel = () => void this.stop(new Error("CUCP operation cancelled; engine stopped. An action may already have occurred. Observe again."));
      const timer = setTimeout(() => void this.stop(new Error("CUCP operation timed out; engine stopped. An action may already have occurred. Observe again.")), this.options.timeoutMs ?? 65_000);
      this.pending = {
        id, command, resolve: resolveRequest, reject,
        cleanup: () => { clearTimeout(timer); signal?.removeEventListener("abort", cancel); },
      };
      signal?.addEventListener("abort", cancel, { once: true });
      if (signal?.aborted) { cancel(); return; }
      let line: string;
      try {
        line = JSON.stringify({ schema: "cucp.request/v1", id, command, args }) + "\n";
        if (Buffer.byteLength(line) > 256 * 1024) throw new Error("CUCP request exceeds 256 KiB");
      } catch (error) {
        this.pending.cleanup();
        this.pending = undefined;
        reject(error);
        return;
      }
      this.child!.stdin.write(line);
    });
  }

  private onData(child: ChildProcessWithoutNullStreams, chunk: Buffer): void {
    if (child !== this.child) return;
    this.buffer = Buffer.concat([this.buffer, chunk]);
    if (this.buffer.length > (this.options.maxResponseBytes ?? 24 * 1024 * 1024)) {
      void this.stop(new Error("CUCP response exceeded byte limit"));
      return;
    }
    const newline = this.buffer.indexOf(10);
    if (newline === -1) return;
    const line = this.buffer.subarray(0, newline).toString("utf8");
    const remainder = this.buffer.subarray(newline + 1);
    // A serial request has exactly one response. Extra stdout is a protocol error.
    if (!this.pending || remainder.length !== 0) {
      void this.stop(new Error("CUCP produced unsolicited or multiple response lines"));
      return;
    }
    const pending = this.pending;
    let response: CucpResponse;
    try { response = parseResponse(line, pending.id, pending.command); }
    catch (error) { void this.stop(new Error(`CUCP protocol error: ${String(error)}`)); return; }
    this.buffer = Buffer.alloc(0);
    this.pending = undefined;
    pending.cleanup();
    if (response.status === "ok") pending.resolve(response);
    else pending.reject(new CucpFailure(response));
  }

  private stop(error: Error): Promise<void> {
    this.epoch++;
    const child = this.child;
    this.child = undefined;
    this.buffer = Buffer.alloc(0);
    if (this.pending) {
      this.pending.cleanup();
      this.pending.reject(error);
      this.pending = undefined;
    }
    if (!child?.pid) return this.stopping;
    const pid = child.pid;
    this.stopping = this.stopping.then(async () => {
      if (process.platform === "win32") {
        // /T includes the native child. Never use a shell or accept a user-supplied PID.
        await new Promise<void>(resolveKill => {
          const killer = spawn("taskkill.exe", ["/PID", String(pid), "/T", "/F"], { windowsHide: true, stdio: "ignore", shell: false });
          const timer = setTimeout(() => { killer.kill(); child.kill(); resolveKill(); }, 5000);
          const done = () => { clearTimeout(timer); resolveKill(); };
          killer.once("error", () => { child.kill(); done(); });
          killer.once("exit", done);
        });
      } else {
        try { process.kill(-pid, "SIGKILL"); }
        catch { child.kill("SIGKILL"); }
      }
    });
    return this.stopping;
  }
}
