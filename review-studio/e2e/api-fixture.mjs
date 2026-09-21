import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const workspace = await mkdtemp(join(tmpdir(), "docs-review-e2e-"));
const apiPort = 8765;
const proxyPort = 4175;
const apiBase = `http://127.0.0.1:${apiPort}`;
const uv = process.platform === "win32" ? join(process.env.LOCALAPPDATA ?? "", "Microsoft", "WinGet", "Packages", "astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe", "uv.exe") : "uv";
const child = spawn(uv, ["run", "--project", root, "python", "-m", "docs.sidecar", "--workspace", workspace, "--health-url", `${apiBase}/health`], { cwd: root, stdio: "inherit", windowsHide: true, env: { ...process.env, DOCS_SIDECAR_CORS_ORIGINS: "http://127.0.0.1:5173" } });
child.on("error", error => { console.error(error); process.exit(1); });
let proxy;
const stop = async () => {
  proxy?.close();
  if (!child.killed) {
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      child.kill("SIGTERM");
    }
  }
  await rm(workspace, { recursive: true, force: true });
};
process.once("SIGINT", async () => { await stop(); process.exit(130); });
process.once("SIGTERM", async () => { await stop(); process.exit(143); });

async function waitForHealth() {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    try { const response = await fetch(`${apiBase}/health`); if (response.ok && (await response.json()).ready === true) return; } catch { /* sidecar is still starting */ }
    await new Promise(resolveDelay => setTimeout(resolveDelay, 250));
  }
  throw new Error("real sidecar did not become healthy");
}
async function request(path, init = {}) {
  const response = await fetch(`${apiBase}${path}`, { ...init, headers: { "content-type": "application/json", ...(init.headers ?? {}) } });
  const body = await response.json();
  if (!response.ok) throw new Error(`${path}: ${response.status} ${JSON.stringify(body)}`);
  return body;
}
async function startProxy() {
  proxy = createServer(async (incoming, outgoing) => {
    const chunks = [];
    for await (const chunk of incoming) chunks.push(chunk);
    const response = await fetch(`${apiBase}${incoming.url}`, { method: incoming.method, headers: incoming.headers, body: chunks.length ? Buffer.concat(chunks) : undefined });
    outgoing.writeHead(response.status, Object.fromEntries(response.headers));
    outgoing.end(Buffer.from(await response.arrayBuffer()));
  });
  await new Promise((resolveListen, reject) => { proxy.once("error", reject); proxy.listen(proxyPort, "127.0.0.1", resolveListen); });
}

await waitForHealth();
const workspaces = await request("/v1/workspaces");
const workspaceId = workspaces.items?.[0]?.id;
if (!workspaceId) throw new Error("real sidecar did not create a workspace");
await request(`/v1/workspaces/${encodeURIComponent(workspaceId)}/select`, { method: "POST", body: JSON.stringify({}) });
await request("/v1/documents/import", { method: "POST", body: JSON.stringify({ workspace_id: workspaceId, filename: "browser-e2e.md", content_base64: Buffer.from(`# REAL BROWSER RUN\n\nThis document is imported through the real API.`).toString("base64"), document_id: "browser-e2e", template: "documento-generico", title: "Real browser run" }) });
await request("/v1/documents/browser-e2e/prepare", { method: "POST", body: JSON.stringify({ workspace_id: workspaceId }) });
const run = await request("/v1/runs", { method: "POST", body: JSON.stringify({ workspace_id: workspaceId, document_id: "browser-e2e", pipeline_id: "document", format: "html", policy: "draft" }) });
let terminal = false;
for (let attempt = 0; attempt < 240; attempt += 1) {
  const current = await request(`/v1/runs/${encodeURIComponent(run.id)}`);
  if (["succeeded", "failed", "cancelled", "expired"].includes(current.status)) { if (current.status !== "succeeded") throw new Error(`real browser run ended as ${current.status}`); terminal = true; break; }
  await new Promise(resolveDelay => setTimeout(resolveDelay, 250));
}
if (!terminal) throw new Error("real browser run timed out");
await startProxy();
process.stdout.write(`real Review Studio fixture ready: ${run.id}`);
setInterval(() => {}, 1000);

