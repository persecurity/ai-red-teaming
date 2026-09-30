# PG-Airlines AI Red-Team Lab

PG-Airlines is a deliberately vulnerable, self-contained AI security range for practicing OWASP LLM Top 10 and MITRE ATLAS techniques. It combines a local Qwen chatbot, mixed-sensitivity RAG, PDF ingestion, over-privileged agents, five cumulative defense levels, and an eight-flag CTF.

> ⚠ Intentionally vulnerable training lab — do not deploy publicly. All data is fake.

The web application and simulated partner gateway bind to `127.0.0.1`; Ollama is reachable only inside the private Compose network. Do not change those bindings or expose the lab to an untrusted network. All names, credentials, records, keys, and payment identifiers in the corpus are synthetic.

## Quick start

Prerequisites: Docker Compose v2, approximately 15 GB free RAM, 6 GB NVIDIA VRAM, and a working NVIDIA Container Toolkit installation.

```sh
chmod +x run.sh
./run.sh
```

Choose a security level from 1 through 5. First startup downloads the selected local Ollama models and may take a while; after those pulls complete, runtime traffic stays within the Compose network. Open <http://127.0.0.1:5001>. The separate reconnaissance target is available at <http://127.0.0.1:8000>.

The launcher waits for the application health check and prints the final browser URL only when the lab is ready. Containers continue running in the background; stop them with `docker compose down`.

Headless startup works as well:

```sh
SECURITY_LEVEL=3 ./run.sh
```

Seeded accounts:

| Role | Username | Password |
|---|---|---|
| Client | `client` | `flysafe123` |
| Admin | `admin` | `toweradmin123` |

The admin dashboard can switch the live defense level without restarting. `POST /api/config/level` accepts `{"level": 1}` through `{"level": 5}` and requires the admin session.

PGBot chat is available directly on the public landing page without an account. Signing in unlocks persistent account chat, boarding-pass uploads, complaint handling, promotion tools, flag submission, and the scoreboard.

## Model profiles

Ollama chooses its packaged GGUF quantization; the named Qwen tags currently use a compact quantization appropriate to this lab. Keep context at 4k, and never raise it beyond 8k on the target hardware: KV-cache growth can evict weights to system RAM and collapse throughput.

Profile A is the default and prioritizes chat quality. The judge reuses the chat weights, saving VRAM but creating correlated blind spots. Llama Guard can cause a model swap at level 4.

```dotenv
MODEL_PROFILE=8B-single
APP_PORT=5001
PARTNER_GATEWAY_PORT=18000
CHAT_MODEL=qwen3:8b
CONFIGURED_JUDGE_MODEL=qwen3:8b
LLAMA_GUARD_MODEL=llama-guard3:1b
EMBED_MODEL=nomic-embed-text
OLLAMA_KEEP_ALIVE=5m
OLLAMA_NUM_CTX=4096
```

Profile B uses a smaller chat model and a different-family judge. It generally raises transfer-attack cost while allowing chat, guard, and judge weights to fit in the 6 GB budget.

```dotenv
MODEL_PROFILE=multi-model-independent-judge
APP_PORT=5001
PARTNER_GATEWAY_PORT=18000
CHAT_MODEL=qwen3:4b
CONFIGURED_JUDGE_MODEL=llama3.2:3b
LLAMA_GUARD_MODEL=llama-guard3:1b
EMBED_MODEL=nomic-embed-text
OLLAMA_KEEP_ALIVE=5m
OLLAMA_NUM_CTX=4096
```

To select a profile, copy its checked-in values to the ignored `.env`, then launch:

```sh
cp .env.profile-b .env
./run.sh
```

Calls to the guard, chat model, judge, and embedding model are made sequentially. At level 5, repeat the same output-side challenge under Profile A and Profile B and compare successful captures; the self-judge's correlated failures are intentional. DLP is regex-based and independent of either judge.

## Langfuse tracing

The chat and agent paths emit one Langfuse trace per request. Chat turns are grouped into sessions, authenticated and guest users receive stable pseudonymous IDs, and each trace contains correctly nested retrieval, embedding, generation, guardrail, evaluator, and tool observations. Ollama model names, parameters, token usage, and timing metadata are attached to the relevant generation or embedding.

Create project API keys in Langfuse under **Settings > API Keys**, then set these values in the ignored `.env` file (do not commit real keys):

```dotenv
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_RELEASE=pg-airlines-local
LANGFUSE_SAMPLE_RATE=1.0
```

Use the base URL for the region or self-hosted instance that issued the keys. Set `LANGFUSE_TRACING_ENVIRONMENT` to keep development, test, and production data separate; set `LANGFUSE_RELEASE` to a deployment version or commit SHA in real deployments. For high-volume deployments, lower `LANGFUSE_SAMPLE_RATE` from `1.0`.

Sensitive strings are redacted client-side immediately before export, including credentials, common PII formats, private keys, and the lab's CTF flags. Tracing is disabled automatically in the test suite and can be disabled at runtime with `LANGFUSE_TRACING_ENABLED=false`.

## Security levels

| Level | Added control |
|---|---|
| 1 | Base system prompt; raw user input, RAG, and model output |
| 2 | Hardened prompt, role pinning, untrusted-context boundaries, and suffix |
| 3 | Regex and suspicious-phrase filtering on typed input |
| 4 | Llama Guard input classification after regex |
| 5 | LLM-as-judge output moderation, followed by deterministic DLP redaction |

Controls are cumulative. L4 and L5 deliberately fail open if the local classifier/judge is unavailable, and this is recorded in server logs. At levels 1–3, PDF text bypasses the typed-input filter. Level 4 PDF guard scanning remains off by default (`SCAN_UPLOADS_WITH_GUARD=false`) so the indirect-injection challenge survives; turn it on to compare behavior.

## Lab surfaces

- The landing page loads an intentionally over-informative chat widget configuration. It reveals a versioned assistant route, feature flags, a service identifier, and the partner gateway location.
- The discovered `/api/v2/assistant` route returns Ollama provider, model, token-count, and timing metadata. The original `/api/chat` route remains as a less verbose legacy endpoint.
- Port 18000 runs a small nginx-style reverse-proxy training facade. It deliberately leaks proxy/version headers and returns distinguishable 200, 401, and 404 responses for route enumeration. It is an emulator, not a full nginx deployment.
- Chat routes PG-Airlines/company questions to RAG and leaves general-knowledge questions on the base model. Relevant chunks come from `rag_corpus/public` and `rag_corpus/sensitive`; Chroma uses `nomic-embed-text`, a BM25 fallback keeps the app inspectable if embeddings are temporarily unavailable, and low-relevance vector hits are discarded.
- RAG responses cite source filenames in the generated answer and expose chunk text plus vector, BM25, and combined relevance scores in `sources`. Non-RAG responses return `sources: []`; `retrieval_info` reports retrieval, generation, and total timings.
- A text-based boarding-pass PDF can be uploaded. Only text is extracted, capped at 5 MB, and stored per user in SQLite for later turns. No PDF content is executed or retained.
- The client discount agent uses a bounded ReAct loop: it can read the filed complaint, then issue an over-authorized discount. The tool result is returned to the model before the request ends.
- The admin promotion agent uses the same loop: it can read recent complaints or the admin boarding pass, then set a promotion or retrieve an internal master code. Retrieved text is untrusted and can influence later tool choices in this intentionally vulnerable lab.
- `POST /api/ctf/submit` validates captures. A flag's base score is multiplied by the active level, and a later higher-level capture upgrades the record.
- `/scoreboard` shows masked capture IDs and totals but never flag values.

Each agent request allows one tool call per model turn, at most four tool calls and five model turns. Unknown or malformed calls are rejected, and a consequential tool can execute only once per request. The routes and response fields remain unchanged. Langfuse records each model invocation and tool action separately under one request trace; private model reasoning is not exposed.

The challenge has no capability or instruction to attack systems outside this Compose project.

## Tests

The fast test suite does not need Ollama or model downloads:

```sh
python -m pytest -q
```

### Promptfoo evaluations

Promptfoo exercises the running chatbot through its public HTTP API. Node.js 24
is pinned in `.nvmrc`, and Promptfoo is installed as a project-local development
dependency so every checkout uses the version recorded in `package-lock.json`.

Install the JavaScript dependencies once:

```sh
nvm use
npm ci
```

Start PG-Airlines in another terminal, then run the functional RAG checks:

```sh
./run.sh
npm run eval
```

The separate security suite describes the behavior expected at defense level 5:

```sh
SECURITY_LEVEL=5 ./run.sh
npm run eval:security
```

Running that suite against level 1 is useful too: failed assertions expose the
lab's intentional data-disclosure weaknesses. Validate configuration without
calling the model with `npm run eval:validate`, and inspect saved results in the
local Promptfoo web UI with `npm run eval:view`.

See [PROMPTFOO_EVALUATIONS.md](PROMPTFOO_EVALUATIONS.md) for a step-by-step
guide to designing test cases, selecting assertions, and adding RAG and security
evaluations.

For a full manual run, verify public RAG answers, each level transition, a PDF upload, both role-specific agents, flag submission, and scoreboard updates. Raw model output is written only to local container logs so instructors can compare it with moderated output.

## Reset

To clear all database records and restore the two seeded accounts while the Compose deployment is running:

```sh
docker compose exec app flask --app wsgi reset-db --yes
```

This command affects only SQLite. To also remove the Chroma index and downloaded models, remove the Compose named volumes:

```sh
docker compose down -v
docker compose up --build
```

## HTTP endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Process health and active level |
| `POST /api/chat` | Public or authenticated PGBot turn |
| `POST /api/v2/assistant` | Deliberately verbose public PGBot endpoint discovered in client JavaScript |
| `POST /api/chat/reset` | Clear the current guest or account chat context |
| `POST /api/upload/boarding-pass` | Extract an authenticated user's PDF |
| `POST /api/agents/discount` | Client discount verifier/tool |
| `POST /api/agents/promotion` | Admin promotion tool runner |
| `POST /api/config/level` | Admin live level switch |
| `POST /api/ctf/submit` | Validate and score a flag |
| `GET /scoreboard` | Human-readable scoreboard |
| `GET :18000/v1/auth` | Public partner authentication descriptor |
| `GET :18000/v1/billing` | Public route that leaks gateway fingerprint headers |
| `GET/POST :18000/v1/chat/completions` | OpenAI-compatible route; returns 401 without the partner Bearer token |

### Example payloads

Send JSON requests with `Content-Type: application/json`. Protected endpoints
also require the session cookie returned after signing in with the appropriate
seeded account.

`POST /api/chat` (public or authenticated):

```json
{
  "message": "When does online check-in open?"
}
```

For curl-oriented exercises, `query` is accepted as an alias for `message`. The response includes
both the legacy `response` field and an `answer` alias, plus a UUID `session_id`.
Send that ID with the next request to continue the same guest conversation without a cookie:

```json
{
  "message": "What about checked bags?",
  "session_id": "2d7d9947-6f46-4fab-a92f-9706fc4e3be0"
}
```

Treat a guest session ID as a bearer token: anyone with it can continue that guest conversation.
The browser can also keep using its session cookie. `POST /api/v2/assistant` returns the same
`session_id` field. For example:

```sh
curl -s -X POST http://127.0.0.1:5001/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is the PG-Airlines baggage policy?"}' | jq
```

Tune conditional retrieval with `RAG_MIN_VECTOR_SCORE` (default `0.35`) and `RAG_TOP_K`
(default `4`). Raising the minimum score makes source activation more selective.

`POST /api/chat/reset` has no request body. It clears the current guest or
authenticated user's chat context; for an authenticated user, it also removes
their uploaded boarding pass.

`POST /api/upload/boarding-pass` does not accept JSON. Send a
`multipart/form-data` body containing a `file` field with a text-based PDF.

`POST /api/agents/discount` (client session required):

```json
{
  "complaint": "My flight was delayed by four hours.",
  "requested_percent": 10
}
```

`POST /api/agents/promotion` (admin session required):

```json
{
  "prompt": "Set a 20 percent promotion for flight PG101."
}
```

`POST /api/config/level` (admin session required):

```json
{
  "level": 3
}
```

The level must be an integer from `1` through `5`.

`POST /api/ctf/submit` (authenticated session required):

```json
{
  "flag": "PGAIR{captured_flag_goes_here}"
}
```

`GET /health` and `GET /scoreboard` have no request body.
