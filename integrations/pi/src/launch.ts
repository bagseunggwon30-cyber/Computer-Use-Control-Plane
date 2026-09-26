import { existsSync } from "node:fs";
import { delimiter, isAbsolute, resolve } from "node:path";

export interface LaunchOptions {
  root: string;
  /** Python executable in source mode; paired with argv for embedding/tests. */
  executable?: string;
  argv?: string[];
  env?: NodeJS.ProcessEnv;
}

/** Select once; an explicitly selected broken bundle must never fall back. */
export function engineLaunch(options: LaunchOptions, live: boolean) {
  const env = { ...process.env, ...options.env };
  const configured = env.CUCP_EXECUTABLE;
  const bundled = resolve(options.root, "CUCP.exe");
  const portable = configured || (!options.executable && !options.argv && existsSync(bundled) ? bundled : undefined);
  let executable: string;
  let argv: string[];
  if (portable && !options.argv) {
    if (!isAbsolute(portable) || /\.(cmd|bat|ps1)$/i.test(portable)) {
      throw new Error("CUCP_EXECUTABLE must be an absolute executable path, not a shell script");
    }
    if (!existsSync(portable)) throw new Error(`CUCP executable not found: ${portable}`);
    executable = portable;
    argv = ["serve"];
    delete env.PYTHONPATH;
    delete env.PYTHONHOME;
  } else {
    const source = resolve(options.root, "pcucp-next", "python");
    if (!options.argv && !existsSync(resolve(source, "pcucp_cli", "__main__.py"))) {
      throw new Error("CUCP engine not found. Keep the portable folder intact or set CUCP_EXECUTABLE to CUCP.exe.");
    }
    env.PYTHONPATH = [source, env.PYTHONPATH].filter(Boolean).join(delimiter);
    executable = options.executable ?? env.CUCP_PYTHON ?? "python";
    argv = options.argv ?? ["-u", "-m", "pcucp_cli", "serve"];
  }
  return { executable, argv: [...argv, ...(live ? ["--allow-live-control"] : [])], env };
}
