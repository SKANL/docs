// Fails when the entry chunk named by dist/index.html is over budget. Run after `npm run build`.
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const RAW_KB = 350;
const GZIP_KB = 110;
// Tripwire for the whole first load (entry + the modulepreloaded vendor chunk), so moving bytes between chunks cannot hide growth.
const INITIAL_GZIP_KB = 150;
const dist = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const html = readFileSync(join(dist, "index.html"), "utf8");
const entry = /<script[^>]+type="module"[^>]+src="([^"]+)"/.exec(html)?.[1];
if (!entry) { console.error("budget: no module script in dist/index.html (run `npm run build` first)"); process.exit(2); }

const bytes = readFileSync(join(dist, entry.replace(/^\//, "")));
const raw = bytes.length / 1000;
const gzip = gzipSync(bytes).length / 1000;
console.log(`entry ${entry}: ${raw.toFixed(2)} kB raw (budget ${RAW_KB}), ${gzip.toFixed(2)} kB gzip (budget ${GZIP_KB})`);
const preloads = [...html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="([^"]+)"/g)].map(match => match[1]);
const initial = [entry, ...preloads].map(file => readFileSync(join(dist, file.replace(/^\//, ""))));
const initialRaw = initial.reduce((sum, chunk) => sum + chunk.length, 0) / 1000;
const initialGzip = initial.reduce((sum, chunk) => sum + gzipSync(chunk).length, 0) / 1000;
console.log(`initial JS (entry + ${preloads.length} preloaded): ${initialRaw.toFixed(2)} kB raw, ${initialGzip.toFixed(2)} kB gzip (gzip budget ${INITIAL_GZIP_KB})`);
if (raw > RAW_KB || gzip > GZIP_KB || initialGzip > INITIAL_GZIP_KB) { console.error("budget: over budget"); process.exit(1); }
