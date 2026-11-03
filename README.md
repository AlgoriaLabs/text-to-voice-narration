# Text to Speech Narration

Text in, voice out: a paid AI service that turns text into natural spoken audio (MP3, Opus or WAV). Agents and apps
pay per call in USDC on **Stellar mainnet** through x402, under
[Provider Standard v1](https://github.com/AlgoriaLabs/stellar-agent-services/blob/main/docs/provider-standard.md).
It registers in the Stellar 8004 registry, so [Stellar Agent Search](https://github.com/berkingurcan/stellar-agent-search)
finds it.

Running it costs nothing:

- **The model is free.** [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache 2.0) runs on the server's CPU
  through ONNX Runtime. There are no per-call API fees and no GPU.
- **The server is free.** It runs on Oracle Cloud's Always Free tier: one Ampere A1 VM (2 OCPUs, 12 GB),
  50 GB of disk and 10 TB of traffic a month. HTTPS comes from Let's Encrypt, through Caddy.
- **Payments cost no XLM per call.** Settlement goes through OpenZeppelin's facilitator, which sponsors the network
  fees (the manifest says `areFeesSponsored`).

## Pricing: by text length

Provider Standard v1 gives each service one fixed price, so length pricing is done as three tiers. An agent picks the
cheapest tier whose limit fits its text. Each tier's `inputSchema` rejects longer text before any payment.

| Service | Text | Speech | Price (USDC) | Charged |
| --- | --- | --- | --- | --- |
| `narrate-short` | up to 500 characters | about 30 s | 0.005 | only when the audio is ready (`on-success`) |
| `narrate-medium` | up to 2,000 characters | about 2 min | 0.02 | only when the audio is ready (`on-success`) |
| `narrate-long` | up to 5,000 characters | about 5 min | 0.05 | when the job starts (`upfront`) |

That works out to about $0.01 per 1,000 characters. To change prices or limits, edit `price` and `text.maxLength` in
`provider.config.json`.
That file is the only place they are set: the gateway and the API both read it.

**Input:** `text` (required), `voice` (41 voices, `af_heart` by default), `speed` (0.5–2) and `format` (`mp3`,
`opus` or `wav`). The voice sets the language: English (US and UK), Spanish, French, Italian, Brazilian Portuguese
and Hindi. **Output:** `audioUrl` (an HTTPS link, valid for 24 hours), `durationSeconds`, `format`, `mimeType`,
`bytes`, `characters`, `voice`, `language`, `sampleRate` and `expiresAt`.

## How it works

```text
agent ──x402 USDC──▶ Caddy (HTTPS, :443) ──▶ Provider Kit gateway (:8787) ──▶ FastAPI + Kokoro (127.0.0.1:8000)
                       │                     manifest, 402 challenge,            text → chunks → parallel
                       │                     payment, job queue, recovery        synthesis → MP3/Opus/WAV
                       └── /audio/<file> ◀───────────── shared volume /data/audio ◀──┘
```

- The **gateway** comes from [`@stellar-agent-services/provider-kit`](https://www.npmjs.com/package/@stellar-agent-services/provider-kit).
  The project was started with `npm create stellar-service -- --kind python --network mainnet`. The gateway publishes
  the manifest at `/.well-known/stellar-agent-services.json`, answers unpaid calls with a 402, verifies and settles
  payments, and keeps jobs in SQLite. A client that loses a response collects it again without paying twice.
- The **API** (`app.py`) knows nothing about payments. It cuts the text into chunks at sentence ends and synthesizes
  one chunk per CPU core at once: on 4 cores, about 2.4× faster than one inference using every core. It saves the
  audio under a random 144-bit name. A job the gateway runs again (same `Idempotency-Key`) gets the same file back.
- **Caddy** terminates HTTPS and serves the audio files straight from the volume. Files are deleted after 25 hours,
  which keeps every link valid for the jobs' 24-hour retention [S8].

Speed: about 45 characters per second on 2 x86 vCPUs, and 60 on 4 ARM cores (an Apple-silicon VM). On the 2-OCPU
A1, expect roughly 30–45 per second, so a full `narrate-long` job takes 2–3 minutes. The gateway learns real job
times and turns callers away (503, before payment) when the queue can't take them in time.

## Run it locally

You need Node.js 22.13 or later, and [uv](https://docs.astral.sh/uv/) or Python 3.10–3.13.

```bash
npm install
npm run models    # downloads Kokoro (310 MB) into models/, checked against pinned SHA-256 hashes
npm test          # API tests, then the whole paid flow offline (fake facilitator, payments signed offline)
```

`E2E_ENGINE=kokoro npm run test:gateway` runs the paid flow with real speech. `npm run dev` starts the API and the
gateway at http://localhost:8787. On mainnet it needs `PAY_TO` and `FACILITATOR_AUTH` first, so run it after the
launch step below. Without uv, set up Python once with
`python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.

## Deploy to Oracle Cloud (Always Free) with Terraform

You need:

- an Oracle Cloud account, with an API key in `~/.oci/config`. In the console, go to Profile → API keys → Add API
  key and save the snippet it shows;
- [Terraform](https://developer.hashicorp.com/terraform/install) 1.5 or later, and an SSH key (`~/.ssh/id_ed25519`);
- a Stellar wallet (Freighter, xBull, Albedo, Hana or a Ledger) holding a few XLM. Its account becomes `PAY_TO`;
- an API key for mainnet's facilitator, from [channels.openzeppelin.com/gen](https://channels.openzeppelin.com/gen).

**1. Create the server.**

```bash
cp .env.example .env                                   # if you don't have one yet
cp infra/oci/terraform.tfvars.example infra/oci/terraform.tfvars   # set tenancy_ocid and region
terraform -chdir=infra/oci init
terraform -chdir=infra/oci apply
```

This creates a network, a firewall (ports 22, 80 and 443) and an Ubuntu 24.04 ARM VM with Docker. Its HTTPS address
is printed as `public_origin`, such as `https://141-148-12-34.sslip.io`. To use your own domain, set `domain` and
point an A record at `public_ip`.

**2. Add the facilitator key.** In `.env`, set `FACILITATOR_AUTH="Bearer <your key>"`.

**3. Go live on mainnet: `npm run launch`.** This opens a page where your wallet approves three things at once: the
USDC trustline on the payout account, the Stellar 8004 registration of your address (what search finds) and a
verification request. It saves `PAY_TO` and `AGENT_ID` in `.env`. No key ever leaves your wallet. On a computer
without a browser, add `-- --no-open` and open the printed link. Launch also warns that the services call
127.0.0.1. That is expected here: the API runs in the same container as the gateway.

**4. Deploy: `terraform -chdir=infra/oci apply`** (or `npm run deploy`). Terraform zips the project and uploads it with
your settings. It then builds the image on the server and starts Caddy and the service. It waits until the public
manifest answers. The first build takes a few minutes, because it downloads the model.

**5. Check it.**

```bash
npm run status                                                    # running, registered, verified?
curl -i -X POST "$(terraform -chdir=infra/oci output -raw public_origin)/services/narrate-short/jobs" \
  -H 'Content-Type: application/json' -d '{"text":"Hello from Stellar."}'          # a 402 with the price: free
npx -y stellar-agent-search@0.1.0 find "text to speech narration"                 # how agents find you
```

The first paid call is yours to make, with an x402 v2 client that supports Stellar's `exact` scheme. Mainnet has no
test money, so nothing here pays by itself.

**Updating.** After any change to the code, `provider.config.json` or `.env`, run `terraform -chdir=infra/oci apply`
again. Only what changed ships. After changing the provider's name or description, run `npm run launch` again; it
updates the registration. For logs, run `ssh ubuntu@<ip> 'cd /opt/narration/app/deploy && sudo docker compose logs -f'`.

### Good to know about the free tier

- **Idle reclaim.** Oracle may reclaim an Always Free VM that stays idle for 7 days (CPU, network and memory under
  20%). A quiet service can look idle. Upgrading the account to Pay As You Go stops this, and you still pay nothing
  within the free limits.
- **Out of host capacity.** If the VM can't be created, try `availability_domain_index = 1` or `2`, try later, or
  upgrade to Pay As You Go.
- **Keep the address.** The address is the server's IP, which is kept for the VM's whole life. Terraform ignores newer
  images and edits to cloud-init, so it won't replace the VM by accident. If you do replace it, the IP changes:
  `assign_reserved_ip = true` or your own `domain` avoids that. Otherwise, run `npm run launch` again to register
  the new address.
- **Terraform state** holds your `FACILITATOR_AUTH`. Keep `infra/oci/terraform.tfstate` private; `.gitignore` already
  covers it.

## Settings

| Variable | Where | What |
| --- | --- | --- |
| `PAY_TO`, `AGENT_ID` | `.env` | The payout account and the 8004 agent id. `npm run launch` saves both. |
| `FACILITATOR_AUTH` | `.env` | `Bearer <key>` for OpenZeppelin's mainnet facilitator |
| `SOROBAN_RPC_URL` | `.env` | Decides uncertain payments from the chain. Default: `https://mainnet.sorobanrpc.com` |
| `TTS_ENGINE` | API | `kokoro`, or `fake` (a tone, for tests; refused on a public https origin) |
| `KOKORO_MODEL` | API, Terraform `kokoro_model` | `kokoro-v1.0.onnx` (default) or `kokoro-v1.0.int8.onnx` (88 MB) |
| `TTS_WORKERS` | API, Terraform `tts_workers` | Chunks read in parallel. Default: one per core. |
| `AUDIO_RETENTION_SECONDS` | API | How long audio files are kept. Default 90,000 (25 hours). |
| `AUDIO_BASE_URL` | API | Where clients fetch audio. Default: `<PUBLIC_ORIGIN>/audio` |

## Files

| File | What it is |
| --- | --- |
| `provider.config.json` | The gateway config: the three tiers, with prices, limits, schemas, examples and capacity |
| `app.py` | The narration API (FastAPI) |
| `narration/` | Text chunking, the Kokoro engine, audio encoding, file storage and expiry, voices, settings |
| `tests/` | API tests (pytest) and the offline end-to-end paid flow (`gateway.test.mjs`) |
| `Dockerfile`, `start.sh` | One image for the API and the gateway (arm64 and amd64) |
| `deploy/` | Docker Compose with Caddy (HTTPS, audio files), and `install.sh`, which the server runs on each deploy |
| `infra/oci/` | Terraform: network, firewall, the A1 VM, cloud-init, and the deploy step |
| `scripts/` | `download-models.sh`, `launch.sh` (`npm run launch`), `python.sh` (runs Python with uv or .venv) |

## Safety

- The server holds no Stellar secret key: only the public `PAY_TO` and the facilitator's API key. Your wallet signs
  the owner steps itself, on a page on your computer.
- This takes real USDC. Uncertain payments are settled from the chain and never charged twice. That is the
  Provider Kit's job recovery, and this project doesn't touch it.
- The API listens only inside its container. Only Caddy's ports 80 and 443 are public, plus SSH. Set
  `ssh_allowed_cidr` to your own address.
