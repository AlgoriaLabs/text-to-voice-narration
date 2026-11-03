// The whole paid flow, offline: the real gateway config and the real API, with a fake facilitator and payments signed
// offline by a throwaway key (the Provider Kit's own test helpers). Nothing touches the network or the chain, and the
// config stays on mainnet (stellar:pubnet), as deployed.
//
//   npm run test:gateway                     # the API with its fake engine (a tone), quick
//   E2E_ENGINE=kokoro npm run test:gateway   # with Kokoro, once scripts/download-models.sh has run
//
// The API is started on 127.0.0.1:8000, where provider.config.json's upstream URLs point.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID, randomBytes } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import { createProvider, loadGatewayConfig } from "@stellar-agent-services/provider-kit";
import { signTestPayment } from "@stellar-agent-services/provider-kit/testing";
import { Keypair } from "@stellar/stellar-sdk";

const API = "http://127.0.0.1:8000";
const USDC_PUBNET = "CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75";
const payTo = Keypair.random().publicKey();
const payer = Keypair.random();
const dataDir = mkdtempSync(join(tmpdir(), "narration-e2e-"));
let api;
let provider;
const settled = [];

const facilitator = {
  verify: async () => ({ isValid: true }),
  settle: async (_payload, requirements) => {
    settled.push(requirements);
    return { success: true, transaction: randomBytes(32).toString("hex"), network: requirements.network };
  },
};

before(async () => {
  const [command, args] = process.env.PYTHON ? [process.env.PYTHON, []] : ["sh", ["scripts/python.sh"]];
  api = spawn(command, [...args, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"], {
    env: { ...process.env, TTS_ENGINE: process.env.E2E_ENGINE ?? "fake", DATA_DIR: dataDir, PUBLIC_ORIGIN: "http://localhost:8787", LOG_LEVEL: "WARNING" },
    stdio: ["ignore", "inherit", "inherit"],
  });
  await waitFor(`${API}/healthz`, 180_000);

  const { config } = await loadGatewayConfig("provider.config.json", {
    env: { PUBLIC_ORIGIN: "http://localhost:8787", PAY_TO: payTo, AGENT_ID: "", JOB_DB_PATH: "memory", FACILITATOR_AUTH: "Bearer test", SOROBAN_RPC_URL: "https://rpc.invalid" },
    overrides: { dev: true },
    openStore: false,
  });
  provider = createProvider({ ...config, facilitator, rpc: false });
});

after(async () => {
  await provider?.close?.();
  api?.kill("SIGTERM");
  rmSync(dataDir, { recursive: true, force: true });
});

test("the manifest offers three mainnet tiers, priced by length", async () => {
  const manifest = await (await call("GET", "/.well-known/stellar-agent-services.json")).json();
  assert.equal(manifest.standard, "stellar-agent-services/provider@1");
  const [accept] = manifest.payment.accepts;
  assert.equal(accept.network, "stellar:pubnet");
  assert.equal(accept.asset, USDC_PUBNET);
  assert.equal(accept.payTo, payTo);
  const tiers = Object.fromEntries(manifest.services.map((s) => [s.name, [s.price.amount, s.inputSchema.properties.text.maxLength, s.charge]]));
  assert.deepEqual(tiers, {
    "narrate-short": ["50000", 500, "on-success"],
    "narrate-medium": ["200000", 2000, "on-success"],
    "narrate-long": ["500000", 5000, "upfront"],
  });
});

test("too long for a tier is refused before any payment is asked for", async () => {
  const response = await createJob("narrate-short", { text: "a".repeat(501) });
  assert.equal(response.status, 400);
  assert.equal((await response.json()).code, "invalid_input");
});

test("an on-success call: 402, then paid, then the audio, charged once", async () => {
  const input = { text: "Welcome back! Your order has shipped and should arrive on Friday.", voice: "af_heart" };
  const challenge = await createJob("narrate-short", input);
  assert.equal(challenge.status, 402);
  const required = JSON.parse(Buffer.from(challenge.headers.get("PAYMENT-REQUIRED"), "base64").toString());
  assert.equal(required.accepts[0].amount, "50000");

  const ids = { "Idempotency-Key": randomUUID(), "Job-Token": randomBytes(32).toString("base64url") };
  const before = settled.length;
  const paid = await createJob("narrate-short", input, { ...ids, "PAYMENT-SIGNATURE": await pay(required.accepts[0]) });
  const job = await finished(paid, ids);
  assert.equal(job.status, "succeeded");
  assert.equal(job.charged, true);
  assert.equal(job.payment.amount, "50000");
  assert.equal(settled.length, before + 1);
  assert.match(job.output.audioUrl, /^http:\/\/localhost:8000\/audio\/[A-Za-z0-9_-]+\.mp3$/);

  const audio = await fetch(job.output.audioUrl.replace("localhost", "127.0.0.1"));
  assert.equal(audio.status, 200);
  assert.equal(audio.headers.get("content-type"), "audio/mpeg");
  assert.equal((await audio.arrayBuffer()).byteLength, job.output.bytes);

  // Collecting the result again never charges [J11].
  const again = await (await call("GET", `/jobs/${ids["Idempotency-Key"]}/result`, undefined, { "Job-Token": ids["Job-Token"] })).json();
  assert.deepEqual(again.output, job.output);
  assert.equal(settled.length, before + 1);
});

test("an upfront call (the long tier) settles first, then narrates", async () => {
  const input = { text: "Bienvenidos a nuestro podcast semanal. ".repeat(10), voice: "ef_dora", format: "opus" };
  const required = JSON.parse(Buffer.from((await createJob("narrate-long", input)).headers.get("PAYMENT-REQUIRED"), "base64").toString());
  assert.equal(required.accepts[0].amount, "500000");
  const ids = { "Idempotency-Key": randomUUID(), "Job-Token": randomBytes(32).toString("base64url") };
  const job = await finished(await createJob("narrate-long", input, { ...ids, "PAYMENT-SIGNATURE": await pay(required.accepts[0]) }), ids);
  assert.equal(job.status, "succeeded");
  assert.equal(job.output.mimeType, "audio/ogg");
  assert.equal(job.output.language, "Spanish");
});

// ---

function call(method, path, body, headers = {}) {
  const init = { method, headers: { ...headers } };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers["Content-Type"] = "application/json";
  }
  return provider.fetch(new Request(`http://localhost:8787${path}`, init));
}

function createJob(service, input, headers) {
  return call("POST", `/services/${service}/jobs`, input, headers);
}

async function pay(requirements) {
  const payload = await signTestPayment(requirements, payer);
  return Buffer.from(JSON.stringify(payload)).toString("base64");
}

/** The job view once it is final: create-job may answer 202 while the job runs. */
async function finished(response, ids) {
  let view = await response.json();
  const deadline = Date.now() + 10 * 60_000;
  while (!["succeeded", "failed"].includes(view.status)) {
    assert.ok([200, 202].includes(response.status), `unexpected ${response.status}: ${JSON.stringify(view)}`);
    assert.ok(Date.now() < deadline, "the job did not finish");
    await new Promise((resolve) => setTimeout(resolve, 1000));
    response = await call("GET", `/jobs/${ids["Idempotency-Key"]}/result`, undefined, { "Job-Token": ids["Job-Token"] });
    view = await response.json();
  }
  return view;
}

async function waitFor(url, ms) {
  const deadline = Date.now() + ms;
  for (;;) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    if (Date.now() > deadline) throw new Error(`${url} did not answer`);
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}
