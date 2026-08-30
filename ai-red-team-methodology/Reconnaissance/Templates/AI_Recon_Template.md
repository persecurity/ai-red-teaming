# AI Application Reconnaissance Template

## 0. Engagement Metadata

| Field | Value |
| --- | --- |
| Target / app name              | `_____` |
| Environment (prod/staging/lab) | `_____` |
| Base URL(s) / host:port        | `_____` |
| Authorization ref / scope doc  | `_____` |
| Rules of engagement / limits   | `_____` |
| Rate-limit constraints         | `_____` |
| Knowledge granted (box color)  | `[ ] black  [ ] grey  [ ] white` |
| Repo access granted?           | `[ ] yes  [ ] no` → path: `_____` |
| Tester / date                  | `_____` |

### Recon posture — the two orthogonal axes

```
Interaction with running target        Knowledge granted before testing
-------------------------------        --------------------------------
Passive → nothing touches runtime      Black-box → no internal access
Active  → craft requests, observe      Grey-box  → partial access
                                       White-box → full source / config
```

- Public repo scraping .......... = passive + black-box
- Granted repo access ........... = passive + white-box (reading code touches no runtime)
- This engagement sits at: **`_____ + _____`**

---

## 1. Passive Reconnaissance

> Gather without directly interacting. Low visibility, but may be stale /
> dev-config / drifted from production.

### 1.1 HTTP header & low-interaction fingerprint

```bash
curl -s -I <TARGET>
```

| Signal | Observed | Notes |
| --- | --- | --- |
| `Server:`                     | `_____` | reverse proxy / gateway? |
| `Via:` / CDN headers          | `_____` | caching / edge? |
| Custom `X-*` / debug headers  | `_____` | framework / upstream leak? |
| Rate-limit headers            | `_____` | limits exposed? |
| Cookies / session hints       | `_____` | auth model? |

### 1.2 Health / status endpoints

Common paths: `/api/health` · `/api/status` · `/-/health` · `/health`

```bash
curl -s <TARGET>/health | jq
```

| Endpoint | Status | What it exposed |
| --- | --- | --- |
| `_____` | `_____` | `_____` |

> Wordlists for endpoint enumeration: chrislockard/api_wordlist, danielmiessler/seclists.

### 1.3 Repository mining (if repo access) — fixed checklist

> Walk the checklist; don't browse randomly. Each file answers a specific question.

```
Repo
 ├── requirements.txt / package.json / pyproject   → stack, AI libs      [ ]
 ├── .env / .env.example / config.py               → models, endpoints   [ ]
 ├── Dockerfile / docker-compose.yml               → services, ports, GPU[ ]
 ├── .github/workflows/                            → deploy, secret names[ ]
 ├── prompts/ *.py *.md *.j2                        → system prompts      [ ]
 ├── tools/ agent.py                                → capabilities, perms [ ]
 ├── rag/ ingest.py                                 → chunking, embeddings[ ]
 ├── tests/ evals/                                  → expected behavior   [ ]
 ├── migrations/ schema.sql                         → data model          [ ]
 └── .git/                                          → history (below)     [ ]
```

Grep patterns:

```
OPENAI_API_KEY|ANTHROPIC_API_KEY|hf_[A-Za-z0-9]   # credentials
system_prompt|SYSTEM_PROMPT                        # prompt logic
chunk_size|chunk_overlap|top_k                     # RAG config
@tool|function_calling|tools=                      # agent capabilities
chromadb|pinecone|weaviate|qdrant|faiss            # vector store
11434|8000|/v1/chat/completions                    # inference endpoints
```

First-pass tooling: `gitleaks`, `trufflehog` (secrets) · `semgrep` (dangerous patterns).

### 1.4 Git history (its own surface)

```bash
git log -p --all -S 'API_KEY'    # every commit adding/removing the string
git log --all --oneline          # message archaeology
```

| History signal | Finding |
| --- | --- |
| Deleted secrets (still in old commits) | `_____` |
| Telling commit messages                 | `_____` |
| Branch / tag names (environments)       | `_____` |
| Author emails (internal domain)         | `_____` |

### 1.5 Cloud vs. local determination

| Axis | Observed | Local ⟶ | ⟵ Cloud |
| --- | --- | --- | --- |
| Credential material | `_____` | no external keys | API keys in env |
| Model pinning       | `_____` | mutable tag | provider version |
| Rate limiting       | `_____` | must build | provider default |
| Blast radius        | `_____` | whole box | scoped to key |

Determination: **`[ ] self-hosted   [ ] cloud   [ ] hybrid`**

---

## 2. Active Reconnaissance

> Direct interaction = runtime truth, but generates logs / may trip alerts /
> consumes rate-limited quota. AI is usually *inside* a web app, not on its own
> port — probe application-layer indicators, not just open ports.

### 2.1 Client-side JS & embedded config

```bash
curl -s <TARGET>/ | grep -iE "<script"
curl -s <TARGET>/js/<file>.js
```

| Config key | Value | Recon value |
| --- | --- | --- |
| apiBase / endpoints    | `_____` | `_____` |
| assistant/chat route   | `_____` | verbose vs minimal? |
| extra service host:port| `_____` | new attack surface |
| serviceId / names      | `_____` | internal naming |
| featureFlags           | `_____` | debug/legacy/AI on? |

### 2.2 Endpoint enumeration — 401 vs 404 technique

> `404` = route absent · `401` = route exists but auth-gated (a real target)

```bash
for e in auth assistants billing chat/completions embeddings files health models status users; do
  code=$(curl -s -o /dev/null -w "%{http_code}" <HOST>/v1/$e)
  echo "/v1/$e - HTTP $code"
done
```

| Endpoint | Code | Interpretation |
| --- | --- | --- |
| `_____` | `_____` | `_____` |

### 2.3 HTTP method enumeration (on a discovered endpoint)

```bash
for m in GET POST PUT DELETE OPTIONS; do
  printf "%-8s " "$m"
  curl -s -o /dev/null -w '%{http_code}\n' -X "$m" <HOST><ENDPOINT>
done
curl -i -X OPTIONS <HOST><ENDPOINT>   # read Allow + proxy headers
```

| Method | Code | Note |
| --- | --- | --- |
| GET / POST / PUT / DELETE / OPTIONS | `_____` | 405 = not allowed |

Gateway / proxy fingerprint (from OPTIONS headers): `Server: _____` · `Via: _____` ·
rate-limit headers: `_____`

---

## 3. Reconstructed Architecture (fill as evidence accrues)

```
User Interface (Web / Mobile / API)        →  _____
        │
        ▼
API Gateway                                 →  _____
        │
        ▼
Orchestration Layer                         →  _____ (framework? custom?)
        ├── RAG Pipeline                     →  _____
        ├── Agent Tools / MCP                →  _____
        └── External Integrations / A2A      →  _____
        │
        ▼
Inference Server                            →  _____ (Ollama / vLLM / TGI?)
        │
        ▼
Underlying Model                            →  _____
```

---

## 4. Layer Enumeration

### 4.1 Model Layer

| Property | Observed | Technique |
| --- | --- | --- |
| Vendor / family / version | `_____` | fingerprinting (below) |
| Context window            | `_____` | marker test |
| Supported languages       | `_____` | probing |
| Knowledge cutoff          | `_____` | cutoff probing |
| Safety / refusal behavior | `_____` | boundary probing |
| Formatting tendencies     | `_____` | style analysis |

**Six fingerprinting techniques** (record result + confidence for each):

1. **Direct identity probing** — ask "what model are you?" — `_____`
2. **Contradiction testing** — assert a false identity, watch for correction
   (weak on ~1B/4B models) — `_____`
3. **Context-window testing** — plant a marker, flood context, ask for recall
   (caveat: serving layer, e.g. Ollama `NUM_CTX`, can cap this at runtime) — `_____`
4. **Capability boundary mapping** — math / logic tasks; compare against a
   known-size local model — `_____`
5. **Knowledge-cutoff probing** — ask cutoff, then verify chronologically
   (Jan→Dec of the claimed year); watch for tool/web access — `_____`
6. **Model-specific behavior** — response style, coding habits, refusal wording
   as a behavioral fingerprint — `_____`

Reference context windows (fingerprint filter, not proof):

```
Qwen3 8B ~40k · Llama3.1 8B ~128k · Qwen3 4B ~256k · Opus-class ~1M
```

Fingerprint conclusion: **`_____`** (confidence: `_____`)

### 4.2 RAG Layer

| Property | Observed | How determined |
| --- | --- | --- |
| Embedding model      | `_____` | config / behavior |
| Vector DB / distance | `_____` | headers / errors / config |
| Chunk size           | `_____` | ⚠ chars or tokens? confirm |
| Chunk overlap        | `_____` | hunt as fragment fingerprint |
| top_k                | `_____` | source count |
| Collections          | `_____` | `sources[].collection` |
| Retrieval thresholds | `_____` | score analysis |
| Fallback behavior    | `_____` | lexical? |

**Is RAG active?** Ask a corpus question vs. a generic question; empty `sources` =
no retrieval. Result: `_____`

**Source metadata fields exposed by the verbose route:**
`[ ] name  [ ] title  [ ] collection  [ ] chunk_id  [ ] text  [ ] vector_score  [ ] bm25_score  [ ] combined_score  [ ] timing`

**Retrieval scoring model (reconstruct the stages):**
1. Keyword router (gate before RAG runs?) — `_____`
2. Vector search min score — `_____`
3. BM25 fallback conditions — `_____`
4. Combined-score weighting — `_____`

**Retrieval-boundary probe** — hold intent constant, weaken the match:

| # | Prompt style | sources? | chunks | vector | bm25 | combined |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | exact terms          | `_____` | | | | |
| 2 | natural synonym      | `_____` | | | | |
| 3 | abstract paraphrase  | `_____` | | | | |
| 4 | misspelled / noisy   | `_____` | | | | |
| 5 | unrelated control    | `_____` | | | | |

**Scoring traps to avoid** (tick when checked):
`[ ]` `sources:[]` may be router reject, not low similarity ·
`[ ]` `vector_score:0` + `bm25>0` = lexical fallback (or embedding down) ·
`[ ]` output moderation can hide sources *after* retrieval ran ·
`[ ]` timing supports a theory but is not proof RAG ran

**Corpus map** (topic → doc → collection; no content copied):

| Topic | Source doc | Collection (public/sensitive) |
| --- | --- | --- |
| `_____` | `_____` | `_____` |

**Data-boundary check:** did a *sensitive* source surface in an *unprivileged*
response? `[ ] yes  [ ] no` → this is a boundary failure, log in §6.

### 4.3 Agent Layer

| Property | Observed | Technique |
| --- | --- | --- |
| Available tools     | `_____` | schema / MCP / repo |
| Tool schemas/params | `_____` | MCP self-describe |
| Permission model    | `_____` | invocation testing |
| Orchestration logic | `_____` | error behavior |

**The gate question for any privileged tool:** *where is the authz check enforced?*
- `[ ]` in the **prompt** → model decides role → confused-deputy, injection-bypassable
- `[ ]` in **orchestration code** → better; does it trust a model-provided role?
- `[ ]` in the **tool implementation** (re-checks session) → real trust boundary

Permission-boundary probe — can the agent: read `_____` · write `_____` ·
execute `_____` · reach external systems `_____` · what's restricted `_____`

**MCP** (if present): JSON-RPC, self-describing. Enumerate tool
name/description/params/param-types/return-types → `_____`

**A2A** (if present): may expose agents, capabilities, tasks, inter-system trust
relationships → `_____`

### 4.4 Infrastructure Layer

| Property | Observed | Technique |
| --- | --- | --- |
| API endpoints        | `_____` | enumeration |
| Backend services     | `_____` | headers / errors |
| Rate limits          | `_____` | response headers |
| Auth mechanism       | `_____` | 401 behavior |
| Server / proxy ID    | `_____` | `Server:` / `Via:` |
| Error formats        | `_____` | malformed requests |
| Inference server     | `_____` | endpoint/format signature |

---

## 5. Recon Matrix (one-line summary per layer)

| Layer | What was enumerated | Key techniques used | Confirmed? |
| --- | --- | --- | --- |
| **Model**          | `_____` | knowledge/capability probing | `_____` |
| **RAG**            | `_____` | chunk/citation/score analysis | `_____` |
| **Agent**          | `_____` | MCP/tool/permission testing | `_____` |
| **Infrastructure** | `_____` | header/endpoint enumeration | `_____` |

---

## 6. Findings Register

> Config-derived weaknesses and runtime boundary failures. Severity is
> provisional pending exploitation.

| # | Finding | Layer | Evidence (artifact, not payload) | Sev | Confirmed |
| --- | --- | --- | --- | --- | --- |
| F1 | `_____` | `_____` | `_____` | `_____` | `[ ]` |
| F2 | `_____` | `_____` | `_____` | `_____` | `[ ]` |


## 7. Recon Summary

**Highest-value recon surface here:** 

**Recon summary:** 

