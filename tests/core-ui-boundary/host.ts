import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";

type Reply = { ok: boolean; result?: unknown; error?: { code: string; detail?: string } };

export class FacadeHost {
  private process: ChildProcessWithoutNullStreams;
  private pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();
  private sequence = 0;
  private stderr = "";

  constructor() {
    const python = process.env.MESH_BOUNDARY_PYTHON ?? (process.platform === "win32"
      ? path.resolve(".venv/Scripts/python.exe") : "python");
    this.process = spawn(python, ["-u", "tests/core-ui-boundary/facade_host.py"], {
      cwd: process.cwd(), env: { ...process.env, PYTHONUTF8: "1" }, stdio: "pipe",
    });
    this.process.stderr.on("data", (data) => { this.stderr += data.toString(); });
    createInterface({ input: this.process.stdout }).on("line", (line) => {
      const { id, reply } = JSON.parse(line) as { id: number; reply: Reply };
      const pending = this.pending.get(id);
      if (!pending) return;
      this.pending.delete(id);
      if (reply.ok) pending.resolve(reply.result);
      else pending.reject(Object.assign(new Error(JSON.stringify(reply.error)), reply.error));
    });
    this.process.on("error", (error) => this.rejectPending(error));
    this.process.on("exit", (code) => this.rejectPending(
      new Error(`Boundary host exited (${code}): ${this.stderr}`)));
  }

  invoke(command: string, args: Record<string, unknown> = {}): Promise<unknown> {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.process.stdin.write(JSON.stringify({ id, command, args }) + "\n");
    });
  }

  async close(): Promise<void> {
    if (this.process.exitCode !== null) return;
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.process.kill();
        reject(new Error("Boundary host did not close within five seconds"));
      }, 5000);
      this.process.once("exit", () => { clearTimeout(timer); resolve(); });
      this.process.stdin.end();
    });
  }

  private rejectPending(error: Error): void {
    for (const pending of this.pending.values()) pending.reject(error);
    this.pending.clear();
  }
}
