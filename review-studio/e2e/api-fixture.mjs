import { createServer } from "node:http";

const runs = [{ id: "fixture-session-1", document: "Fixture safety case", template: "Fixture template", startedAt: "Sep 19, 2026 · 10:00", duration: "1m 02s", status: "passed", findings: 1, artifactCount: 2 }];
const findings = [{ id: "FIX-001", title: "Fixture finding", severity: "high", status: "failed", location: "§1 · Fixture · p. 1", summary: "A finding served by the local browser fixture.", owner: "Fixture", updated: "Just now" }];
const graph = { nodes: [{ id: "fixture-claim", label: "Fixture claim", kind: "claim", confidence: 0.9, x: 50, y: 35 }, { id: "fixture-source", label: "Fixture source", kind: "source", confidence: 1, x: 25, y: 70 }], edges: [{ source: "fixture-source", target: "fixture-claim", relation: "supports" }] };

function sendJson(response, body) {
  response.writeHead(200, { "content-type": "application/json", "access-control-allow-origin": "http://127.0.0.1:5173" });
  response.end(JSON.stringify(body));
}

const server = createServer((request, response) => {
  if (request.method === "OPTIONS") {
    response.writeHead(204, { "access-control-allow-origin": "http://127.0.0.1:5173", "access-control-allow-methods": "GET, OPTIONS", "access-control-allow-headers": "content-type" });
    response.end();
    return;
  }
  if (request.url === "/v1/runs") return sendJson(response, { items: runs });
  if (request.url === "/v1/findings") return sendJson(response, { items: findings });
  if (request.url === "/v1/graph") return sendJson(response, graph);
  if (request.url === "/v1/runs/fixture-session-1/progress") {
    response.writeHead(200, { "content-type": "text/event-stream", "access-control-allow-origin": "http://127.0.0.1:5173" });
    response.end("data: {\"type\":\"progress\",\"progress\":1,\"message\":\"Fixture complete\"}\n\n");
    return;
  }
  if (request.url?.startsWith("/v1/")) return sendJson(response, { items: [] });
  response.writeHead(404);
  response.end();
});

server.listen(4174, "127.0.0.1");
