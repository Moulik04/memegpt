// Throwaway local verification script — NOT part of the shipped Worker.
// Spins up a mock backend + `wrangler dev` (no real Cloudflare deploy, no
// real Discord traffic), signs test requests with a locally-generated
// ed25519 keypair the same way Discord signs real ones, and asserts the
// Worker's PING/PONG handshake and deferred-ack + forward-to-backend flow
// both work end to end.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import nacl from "tweetnacl";
import fs from "node:fs";

const kp = nacl.sign.keyPair();
const publicKeyHex = Buffer.from(kp.publicKey).toString("hex");
const SHARED_SECRET = "test-shared-secret-123";
const MOCK_BACKEND_PORT = 9797;
const WORKER_PORT = 8797;

fs.writeFileSync(
  new URL("./.dev.vars", import.meta.url),
  `DISCORD_PUBLIC_KEY=${publicKeyHex}\nDISCORD_WORKER_SHARED_SECRET=${SHARED_SECRET}\n`,
);

function sign(body, timestamp) {
  const message = Buffer.from(timestamp + body);
  const sig = nacl.sign.detached(message, kp.secretKey);
  return Buffer.from(sig).toString("hex");
}

let receivedByBackend = null;
const mockBackend = createServer((req, res) => {
  let chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    receivedByBackend = {
      path: req.url,
      secretHeader: req.headers["x-discord-worker-secret"],
      body: JSON.parse(Buffer.concat(chunks).toString() || "{}"),
    };
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ meme_url: "/static/generated/testmeme01.png", template_id: "drake" }));
  });
});

await new Promise((resolve) => mockBackend.listen(MOCK_BACKEND_PORT, resolve));
console.log(`Mock backend listening on :${MOCK_BACKEND_PORT}`);

const wrangler = spawn(
  "npx",
  ["wrangler", "dev", "--port", String(WORKER_PORT), "--var", `BACKEND_URL:http://localhost:${MOCK_BACKEND_PORT}`],
  { cwd: new URL(".", import.meta.url).pathname, stdio: ["ignore", "pipe", "pipe"] },
);

let wranglerReady = false;
wrangler.stdout.on("data", (d) => {
  const s = d.toString();
  if (s.includes("Ready on") || s.includes(`localhost:${WORKER_PORT}`)) wranglerReady = true;
});
wrangler.stderr.on("data", (d) => process.stderr.write(`[wrangler stderr] ${d}`));

async function waitForWorker(timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const r = await fetch(`http://localhost:${WORKER_PORT}/`, { method: "POST", body: "{}" });
      // Any response (even 401) means the server is up and routing requests.
      if (r.status) return true;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

let exitCode = 0;
try {
  const up = await waitForWorker();
  if (!up) throw new Error("wrangler dev never became reachable");
  console.log("wrangler dev is up.");

  // --- Test 1: PING -> PONG ---
  const pingBody = JSON.stringify({ type: 1 });
  const pingTs = String(Math.floor(Date.now() / 1000));
  const pingResp = await fetch(`http://localhost:${WORKER_PORT}/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Signature-Ed25519": sign(pingBody, pingTs),
      "X-Signature-Timestamp": pingTs,
    },
    body: pingBody,
  });
  const pingJson = await pingResp.json();
  if (pingResp.status !== 200 || pingJson.type !== 1) {
    throw new Error(`PING test failed: status=${pingResp.status} body=${JSON.stringify(pingJson)}`);
  }
  console.log("PASS: PING -> PONG (type 1)");

  // --- Test 2: invalid signature is rejected ---
  const badResp = await fetch(`http://localhost:${WORKER_PORT}/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Signature-Ed25519": "0".repeat(128),
      "X-Signature-Timestamp": pingTs,
    },
    body: pingBody,
  });
  if (badResp.status !== 401) {
    throw new Error(`Expected 401 for bad signature, got ${badResp.status}`);
  }
  console.log("PASS: invalid signature rejected with 401");

  // --- Test 3: /meme command -> deferred ack + background forward ---
  const cmdBody = JSON.stringify({
    type: 2,
    token: "fake-interaction-token",
    application_id: "fake-app-id",
    data: { name: "meme", options: [{ name: "text", value: "waiting for the build to finish" }] },
  });
  const cmdTs = String(Math.floor(Date.now() / 1000));
  const cmdResp = await fetch(`http://localhost:${WORKER_PORT}/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Signature-Ed25519": sign(cmdBody, cmdTs),
      "X-Signature-Timestamp": cmdTs,
    },
    body: cmdBody,
  });
  const cmdJson = await cmdResp.json();
  if (cmdResp.status !== 200 || cmdJson.type !== 5) {
    throw new Error(`/meme command test failed: status=${cmdResp.status} body=${JSON.stringify(cmdJson)}`);
  }
  console.log("PASS: /meme command -> deferred ack (type 5) within the response itself");

  // Give the background waitUntil() task a moment to hit the mock backend.
  await new Promise((r) => setTimeout(r, 1500));
  if (!receivedByBackend) {
    throw new Error("Mock backend never received the forwarded request from the Worker's background task");
  }
  if (receivedByBackend.path !== "/discord/generate") {
    throw new Error(`Wrong path forwarded: ${receivedByBackend.path}`);
  }
  if (receivedByBackend.secretHeader !== SHARED_SECRET) {
    throw new Error(`Shared secret header mismatch: got ${receivedByBackend.secretHeader}`);
  }
  if (receivedByBackend.body.text !== "waiting for the build to finish") {
    throw new Error(`Wrong text forwarded: ${JSON.stringify(receivedByBackend.body)}`);
  }
  console.log("PASS: background task forwarded the correct text + shared secret to the backend");

  console.log("\nAll local Worker verification checks passed.");
} catch (err) {
  console.error("FAIL:", err.message);
  exitCode = 1;
} finally {
  wrangler.kill("SIGTERM");
  mockBackend.close();
  fs.rmSync(new URL("./.dev.vars", import.meta.url), { force: true });
}

process.exit(exitCode);
