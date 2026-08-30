# AI Application Reconnaissance Template — FILLED: PG-Airlines Lab

### Recon posture — the two orthogonal axes

- Reading lab source = **passive + white-box** (touches no runtime).
- Probing the live endpoints = **active** against the same white-box knowledge.
- This engagement sits at: **passive + white-box, then active validation**.

---

## 1. Passive Reconnaissance

### 1.1 HTTP header & low-interaction fingerprint

Method demonstrated against a public site (`curl -s -I onet.pl`) — headers leaked
`Server: Ring Publishing - Accelerator`, CloudFront `Via`/`X-Amz-Cf-*`, cookies.
Same technique to be pointed at the lab app; treat as **low-interaction**, not
strictly passive.

### 1.2 Health / status endpoints

| Endpoint                                    | Status | What it exposed                                                                                                                                         |
| ------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/health` (a separate lab agent, port 7003) | 200 ok | agent name/id, protocol, `securityLevel: critical`, and a **tool list** (`read_file`, `write_file`, `execute_command`, `send_email`, `access_database`) |

> A health endpoint returning a full tool inventory is itself a finding — see F-series.

### 1.3 Repository mining (white-box) — checklist results

| Checklist item             | Finding                                                                                                                                                                            |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `requirements.txt` → stack | Flask 3.1.1, Flask-Login 0.6.3, Werkzeug 3.1.3, requests 2.32.4, **pypdf 5.6.0** (PDF ingest → boarding-pass injection vector), **chromadb 1.0.12**, gunicorn 23.0.0, pytest 8.4.1 |
| `config.py` → blueprint    | See §1.5 + Findings. Ollama runtime, `qwen3:8b` chat, `llama-guard3:1b` guard, `nomic-embed-text` embeddings, Chroma paths, ctx 4096, 5 MB upload cap                              |
| `rag.py` → retrieval       | collections `public` + `sensitive`; chunk 900 / overlap 120; persistent Chroma, cosine; `top_k=4`; lexical fallback                                                                |
| `agent.py` → tools         | 3 tools with role gates (see §4.3)                                                                                                                                                 |
| `prompts.py` → prompts     | PGBot persona; level-1 vs level-≥2 boundary sets (see §4.1 / Findings)                                                                                                             |
| env / model supply chain   | `MODEL_PROFILE=8B-single`, `APP_PORT=5001`, chat+judge both `qwen3:8b`, guard `llama-guard3:1b`, embed `nomic-embed-text`, `KEEP_ALIVE=5m`, `NUM_CTX=4096`                         |

### 1.4 Git history

Not exercised in this lab (method noted for real engagements: `git log -p --all -S`,
message archaeology, branch/tag environments, author-email domain leak — same
forensic muscle as auditing AI-generated recruitment submissions).

### 1.5 Cloud vs. local determination

| Axis                | Observed (this lab)                            |
| ------------------- | ---------------------------------------------- |
| Credential material | no external keys                               |
| Model pinning       | **mutable tag** `qwen3:8b` (not digest-pinned) |
| Rate limiting       | present at gateway (60/min)                    |
| Blast radius        | whole box (infra + weights + data)             |

Determination: **`[x] self-hosted`** — removes provider exposure but shifts
infra/access/service hardening onto the operator.

---

## 2. Active Reconnaissance

> Note: AI is embedded in the web app, not on a dedicated port — probing focused on
> JS config, API routes, and response patterns rather than pure port scanning.

### 2.1 Client-side JS & embedded config

`curl -s .../ | grep -iE "<script"` → `/js/passenger-support.js`, `/js/main.js`.
`passenger-support.js` exposes `window.__PGAIR_CONFIG__`:

| Config key        | Value                                                                     | Recon value                                 |
| ----------------- | ------------------------------------------------------------------------- | ------------------------------------------- |
| apiBase           | `/api/v2`                                                                 | base path                                   |
| assistantEndpoint | `/api/v2/assistant`                                                       | **verbose** chat route (best for RAG recon) |
| partnerGateway    | host `:18000`                                                             | additional service surface                  |
| serviceId         | `pgair-passenger-support`                                                 | internal naming                             |
| featureFlags      | `enableAI:true, debugMode:false, legacySupport:true, partnerBilling:true` | AI on, legacy + billing paths               |

("Internal Use Only" comment present — not an access control, but signals intent.)

Direct hit on `/api/v2/assistant` (POST JSON `{"message":"Hello"}`) returned:
`metadata.model = qwen3:8b`, `metadata.provider = ollama`, plus token/timing data;
and a `sources[]` array already containing **both** `public` docs and **`sensitive`**
docs (`passengers.md`, `pilots.md`) — RAG confirmed + data-boundary leak on first
contact.

### 2.2 Endpoint enumeration — 401 vs 404 (on `:18000/v1/*`)

`nmap` first flagged port `18000`. Bash loop over `/v1/*`:

| Endpoint                                                                       | Code | Interpretation                       |
| ------------------------------------------------------------------------------ | ---- | ------------------------------------ |
| `/v1/auth`                                                                     | 200  | accessible                           |
| `/v1/billing`                                                                  | 200  | accessible                           |
| `/v1/chat/completions`                                                         | 401  | **exists, auth-gated** (real target) |
| `/v1/assistants` `/embeddings` `/files` `/health` `/models` `/status` `/users` | 404  | absent                               |

### 2.3 HTTP method enumeration — on `/v1/chat/completions`

| Method  | Code | Note                      |
| ------- | ---- | ------------------------- |
| GET     | 401  | supported, auth required  |
| POST    | 401  | supported, auth required  |
| PUT     | 405  | not allowed               |
| DELETE  | 405  | not allowed               |
| OPTIONS | 200  | accepted **without** auth |

`OPTIONS` full headers → `Allow: POST, OPTIONS, HEAD, GET` ·
**`Server: nginx/1.26.3`** · **`Via: 1.1 kong/3.9.1`** (Kong gateway) ·
rate-limit headers: `RateLimit-Limit: 60` / `-Remaining` / `-Reset` (≈60/min) ·
`X-Kong-Upstream-Latency` / `-Proxy-Latency` timing exposed.

---

## 3. Reconstructed Architecture

```
Flask + Flask-Login (UI / auth)              :5001
        │
        ▼
gunicorn  ───────────────── no dedicated gateway in the app itself
        │                    (Kong 3.9.1 + nginx 1.26.3 front the :18000 partner API)
        ▼
Orchestration (custom, no framework)
        ├── RAG: Chroma (public | sensitive), 900/120, cosine, top_k=4
        │        embed: nomic-embed-text        fallback: lexical (BM25)
        ├── Tools: issue_discount | set_promotion | get_master_code
        └── Guard: llama-guard3:1b (upload scanning OFF by default)
        │
        ▼
Ollama :11434   (KEEP_ALIVE 5m, NUM_CTX 4096)
        │
        ▼
qwen3:8b   (also serves as the judge model)
```

---

## 4. Layer Enumeration

### 4.1 Model Layer

| Property                  | Observed                                               | Technique             |
| ------------------------- | ------------------------------------------------------ | --------------------- |
| Vendor / family / version | Qwen (Alibaba); served model `qwen3:8b`                | metadata + config     |
| Context window            | `NUM_CTX=4096` (runtime cap; base Qwen3 8B ≈ 40k)      | config / caveat below |
| Knowledge cutoff          | (Qwen 2.5 self-reported Oct 2023 in the terminal demo) | cutoff probing        |
| Safety / refusal behavior | PGBot refusal strings; persona lock at level ≥2        | prompt review         |
| Runtime provider          | Ollama                                                 | response metadata     |

**Six fingerprinting techniques — as practiced (on local Qwen/Llama/Mistral):**

1. **Direct identity probing** — Qwen 2.5 via Ollama self-IDs as "Qwen … by Alibaba
   Cloud"; Mistral self-IDs as "created by Mistral AI". PGBot itself is scope-locked,
   so direct probing is the _baseline_ step, not the finish.
2. **Contradiction testing** — false "you're Grok/xAI" prompt → model volunteered a
   correction revealing true identity (Qwen). Noted **weak on 1B/4B** models.
3. **Context-window testing** — plant marker (`Remember this secret word: PANAMA`),
   flood context, ask for recall. **Caveat applied:** Ollama `NUM_CTX` caps this at
   runtime (4096 here), so the observed limit reflects config, not the base model.
4. **Capability boundary mapping** — `958 * 121` and a 5-person ordering puzzle,
   run on **Qwen3 8B vs 4B** as a size cross-check. Both correct (115,918 / correct
   order); 4B was actually the tidier writeup. Consistent boundaries ⇒ supports the
   estimated size band (larger 70B+ more consistent on long chains; ~3B error-prone).
5. **Knowledge-cutoff probing** — Qwen 2.5 claimed Oct 2023; verified by asking about
   post-cutoff events (e.g. "Anthropic Opus release" → model denied such a model),
   repeated for determinism, then refine month-by-month; watch for web/tool access.
6. **Model-specific behavior** — ELI-12 biotech + FizzBuzz across Qwen 2.5 / Qwen
   Coder / Llama 3.1: Qwen concise & structured, Llama longer & more example-driven,
   Qwen Coder adds docstrings + list-comprehension variant. Style = behavioral
   fingerprint that survives system-prompt changes.

Fingerprint conclusion: **Qwen3 8B served via Ollama** (confidence: high — corroborated
by config, response metadata, and behavior).

### 4.2 RAG Layer

| Property             | Observed                                          | How determined                                     |
| -------------------- | ------------------------------------------------- | -------------------------------------------------- |
| Embedding model      | `nomic-embed-text`                                | config                                             |
| Vector DB / distance | persistent Chroma, cosine                         | `rag.py`                                           |
| Chunk size           | 900                                               | ⚠ confirm chars vs tokens (900 chars ≈ 225 tokens) |
| Chunk overlap        | 120                                               | fragment fingerprint to hunt in returned text      |
| top_k                | 4                                                 | source count                                       |
| Collections          | `public`, `sensitive`                             | `sources[].collection`                             |
| Vector threshold     | min vector score `0.35`                           | `rag.py` / scoring                                 |
| Fallback             | BM25 lexical when vectors unavailable / below min | `rag.py`                                           |

**Is RAG active?** Yes — corpus question ("refund policy") returned a
`refunds-and-rebooking.md` source; generic question ("first letter of the alphabet")
returned `sources: []` (base model only).

**Source metadata fields exposed by `/api/v2/assistant`:**
`[x] name [x] title [x] collection [x] chunk_id [x] text [x] vector_score [x] bm25_score [x] combined_score [x] timing` — a very verbose route.

**Retrieval scoring model (3 stages, reconstructed):**

1. Small **keyword router** decides if the question looks airline-related (gate before RAG).
2. **Vector search**, default min score `0.35`.
3. **BM25** fallback when vectors unavailable / all below min.
   Combined score weights vector > normalized BM25.

**Retrieval-boundary probe set** (hold intent, weaken match):
`baggage allowance?` → `how much luggage…?` → `what can a traveller carry…?` →
`how much lugage… flite?` (misspelled) → `how do plants make food?` (control).
Expectation: exact terms strengthen BM25; synonyms still hit via vectors; noisy
spelling degrades both; control stays on base model with no sources.

**Scoring traps flagged:**
`[x]` `sources:[]` may be **router reject**, not low similarity ·
`[x]` `vector_score:0` + `bm25>0` = **lexical fallback** (or embedding down) ·
`[x]` level-5 output moderation can hide sources _after_ retrieval ran ·
`[x]` timing supports but does not prove RAG ran.

**Corpus map (8 docs; content not copied):**

| Topic                                | Source doc                    | Collection    |
| ------------------------------------ | ----------------------------- | ------------- |
| Baggage                              | `baggage.md`                  | public        |
| Check-in / fares                     | `checkin-and-fares.md`        | public        |
| Delays / cancellations               | `delays-and-cancellations.md` | public        |
| Loyalty                              | `loyalty.md`                  | public        |
| Refunds / rebooking                  | `refunds-and-rebooking.md`    | public        |
| Passenger records                    | `passengers.md`               | **sensitive** |
| Pilot roster                         | `pilots.md`                   | **sensitive** |
| Internal ops memo (fake creds/infra) | internal ops memo             | **sensitive** |

**Data-boundary check:** `[x] yes` — sensitive sources (`passengers.md`, `pilots.md`)
surfaced in an unprivileged assistant response → boundary failure (F5).
DLP note: levels 1–4 return snippets unredacted; level 5 may block the answer,
strip sources, or redact patterns — compare the _same_ question across levels to
isolate which layer changed the result.

### 4.3 Agent Layer

| Property         | Observed                                                                                                                                                                 |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Available tools  | `issue_discount(percent)` (client-only) · `set_promotion(flight_id, discount_percent)` (admin-only) · `get_master_code()` (admin-only, returns internal code / CTF flag) |
| Permission model | role-gated (client vs admin)                                                                                                                                             |

**Gate question — where is admin/client authz enforced?** Open item to confirm:

- `[ ]` prompt → confused-deputy, injection-bypassable
- `[ ]` orchestration → check if it trusts a model-provided role
- `[ ]` tool implementation (re-checks session) → real boundary

White-box repo access is the low-cost way to answer this (H4). For reference, a
framework project (e.g. CrewAI) would expose structure via `@CrewBase`/`@agent`/
`@task`/`@crew` decorators — PG-Airlines is custom, no framework.

**MCP / A2A:** not exercised in this lab (no MCP server or A2A endpoint present).
Method retained for targets that expose them.

### 4.4 Infrastructure Layer

| Property          | Observed                                                                |
| ----------------- | ----------------------------------------------------------------------- |
| API endpoints     | `/api/v2/assistant` (app) · `:18000/v1/{auth,billing,chat/completions}` |
| Rate limits       | 60/min at the `:18000` gateway                                          |
| Auth mechanism    | 401 gating on `/v1/chat/completions`, GET+POST                          |
| Server / proxy ID | nginx 1.26.3 behind Kong 3.9.1                                          |
| Inference server  | Ollama `:11434` (`/api/tags` would list model inventory if reachable)   |
| Timing leakage    | Kong upstream/proxy latency headers exposed                             |

---

## 5. Recon Matrix

| Layer              | What was enumerated                                                                      | Key techniques used                                      | Confirmed? |
| ------------------ | ---------------------------------------------------------------------------------------- | -------------------------------------------------------- | ---------- |
| **Model**          | Qwen3 8B via Ollama; ctx 4096; also the judge                                            | metadata + 6 fingerprinting techniques                   | yes        |
| **RAG**            | Chroma public+sensitive, 900/120, cosine, top_k=4, min 0.35, BM25 fallback; 8-doc corpus | verbose source metadata, boundary probing, score reading | yes        |
| **Agent**          | 3 role-gated tools; gate location TBC                                                    | repo review (invocation testing pending)                 | partial    |
| **Infrastructure** | Kong 3.9.1 + nginx 1.26.3, 60/min, :18000 gateway, Ollama :11434                         | 401/404, method enum, OPTIONS headers                    | yes        |

---

## 6. Findings Register

| #   | Finding                                                                                                                             | Layer              | Evidence (artifact, not payload)        | Sev  | Confirmed |
| --- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------ | --------------------------------------- | ---- | --------- |
| F1  | `SECRET_KEY` hardcoded fallback → forgeable Flask sessions if env unset (matters because tool perms look session-role-based)        | Infra/Agent        | `config.py`                             | high | `[x]`     |
| F2  | `SCAN_UPLOADS_WITH_GUARD=False` default → uploads reach pipeline unscreened (poisoned PDF/boarding pass)                            | RAG/Infra          | `config.py` + pypdf ingest              | high | `[x]`     |
| F3  | `JUDGE_MODEL` defaults to `CHAT_MODEL` → model judges its own output; one injection compromises both                                | Model              | `config.py`                             | med  | `[x]`     |
| F4  | Guard is `llama-guard3:1b` (content-category classifier, **not** a prompt-injection defense)                                        | Model/Infra        | `config.py`                             | med  | `[x]`     |
| F5  | Public + sensitive collections share one index; sensitive docs returned to unprivileged query                                       | RAG                | `sources[].collection` in live response | high | `[x]`     |
| F6  | Verbose `/api/v2/assistant` leaks chunk_id, raw text, scores, timing → corpus mapping                                               | RAG/Infra          | live response fields                    | med  | `[x]`     |
| F7  | Level-1 secret protected only by a "never volunteer it" instruction (prompt rule ≠ trust boundary)                                  | Model              | `prompts.py`                            | high | `[x]`     |
| F8  | `OLLAMA_BASE_URL :11434` — if reachable beyond localhost unauthenticated, exposes model mgmt/inference; `/api/tags` leaks inventory | Infra              | `config.py`                             | med  | to test   |
| F9  | Mutable model tag `qwen3:8b` (not digest-pinned) → served weights can change without config change                                  | Model supply chain | env / config                            | low  | `[x]`     |
| F10 | Small context (4096) vs top_k 4 × 900 chars → context crowding / instruction displacement plausible                                 | Model/RAG          | config math                             | low  | to test   |
| F11 | Privileged-tool authz location unconfirmed; if enforced in prompt → confused-deputy                                                 | Agent              | `agent.py` + `prompts.py`               | high | to test   |

---

## 7. Recon Summary

**Highest-value recon surface here:** the verbose `/api/v2/assistant` route — a
client-side config file walked us from "AI endpoint exists" to model, provider, RAG
architecture, and data-classification structure in one request.

**Recon summary:** the core weakness is that **public and internal files are searched together** while the verbose API
returns enough metadata to map the corpus and reverse-engineer ranking.
