# AI Red Teaming

A self-contained workbench for practicing offensive testing of LLM applications. It combines a deliberately vulnerable target, command-line probes, and a reusable methodology that documents how to map an AI application's attack surface before testing it.

Everything runs locally: the target ships as a Docker Compose project with local Ollama models, and the probes are single-binary Go commands. No external AI provider or API key is involved.

> ⚠ Intentionally vulnerable training material. Run it only on a machine you control, and only against systems you own or are explicitly authorized to test. All lab data is synthetic.

## Layout

```
ai-red-teaming/
├── ai-red-team-labs/
│   └── PG-Airlines/     Vulnerable airline support app (Flask + Ollama + RAG + agents + CTF)
├── ai-red-team-methodology/
│   ├── 01-reconnaissance/  Theory, practical workflow, templates, and a completed example
│   └── flashcards/         AI security study deck
└── tools/               Go probes for driving a chat API and grading responses
    └── cmd/             prompt-fuzzer, injection-classifier, determinism-probe, rate-limit-probe
```

Each part has its own README with full detail:

- [ai-red-team-labs/PG-Airlines/README.md](ai-red-team-labs/PG-Airlines/README.md) — lab setup, model profiles, security levels, endpoints
- [ai-red-team-methodology/README.md](ai-red-team-methodology/README.md) — guided learning path, reconnaissance theory, practical exercises, and assessment templates
- [tools/README.md](tools/README.md) — probe usage, flags, expected chat API structure

## How the pieces fit together

```mermaid
flowchart LR
    M[Methodology<br/>plan and document] --> L[PG-Airlines lab<br/>exercise attack paths]
    T[Go probes<br/>replay and measure] --> L
    L --> E[Evidence<br/>responses and findings]
    E --> M
```

## The target: PG-Airlines

A fake airline's support portal, built to expose a realistic slice of the OWASP LLM Top 10 and MITRE ATLAS techniques:

- **PGBot chat** backed by a local Qwen model, reachable without an account
- **Mixed-sensitivity RAG** — public policy documents and sensitive passenger/pilot/internal records share one retrieval index
- **PDF ingestion** — boarding-pass text is extracted into later model context, an indirect injection path
- **Over-privileged agents** — a client discount tool and an admin promotion tool that trust LLM decisions too much
- **Five cumulative defense levels**, switchable live from the admin dashboard, from a bare system prompt up to Llama Guard input classification plus LLM-as-judge and regex DLP on output
- **Eight-flag CTF** with level-weighted scoring and a scoreboard

The interesting exercise is not just capturing a flag at level 1, but re-running the same technique as controls stack up and observing where each one actually holds.

## The methodology

The methodology turns ad hoc probing into an evidence-driven assessment. Its first phase covers passive and active reconnaissance across four distinct surfaces: the model, retrieval pipeline, agents and tools, and supporting infrastructure.

Start with the [methodology learning path](ai-red-team-methodology/README.md), use the blank reconnaissance template during an assessment, and compare the result with the completed PG-Airlines example. A CSV flashcard deck is included for review and import into spaced-repetition tools.

## The probes

Four Go commands under [tools/cmd/](tools/cmd/), all speaking the same JSON chat API (`http://localhost:5001/api/chat` by default):

| Command                | Purpose                                                                |
| ---------------------- | ---------------------------------------------------------------------- |
| `prompt-fuzzer`        | Replay a CSV of prompts at a bounded request rate, save every response |
| `injection-classifier` | Grade fuzzer output with a local Ollama model as LLM judge             |
| `determinism-probe`    | Send one prompt repeatedly to measure response consistency and length  |
| `rate-limit-probe`     | Find where the target starts returning `429`                           |

## Prerequisites

| For                    | You need                                                                       |
| ---------------------- | ------------------------------------------------------------------------------ |
| The lab                | Docker Compose v2, ~15 GB free RAM, 6 GB NVIDIA VRAM, NVIDIA Container Toolkit |
| The probes             | Go 1.20 or newer                                                               |
| `injection-classifier` | A local Ollama install with a judge model pulled                               |

## End-to-end run

Start the target at a chosen defense level:

```sh
cd ai-red-team-labs/PG-Airlines
chmod +x run.sh
./run.sh              # or: SECURITY_LEVEL=3 ./run.sh
```

First startup pulls the local models and takes a while. The launcher waits for the health check, then prints <http://127.0.0.1:5001>. Sign in as `client` / `flysafe123` or `admin` / `toweradmin123`.

Fire a corpus at it and grade the results:

```sh
cd ../../tools
go run ./cmd/prompt-fuzzer 15 csv/direct_injection.csv -o results.csv
go run ./cmd/injection-classifier results.csv
```

`injection-classifier` rewrites its input file in place, so copy anything you want to keep. Treat its `SUCCESS` / `POSSIBLE` / `NO_SUCCESS` labels as triage, not verdicts — confirm the interesting rows by hand.

Then raise the level through the admin dashboard (or `POST /api/config/level`) and replay the same corpus to see which techniques survive.

Shut the lab down with `docker compose down`, or `docker compose down -v` to also drop the Chroma index and downloaded models.

## Handling results

CSV reports contain attack prompts and raw model output, sometimes including the lab's synthetic PII and canaries. Keep them out of version control and off shared storage. High request rates cost throughput and can degrade the target, so start `rate-limit-probe` low and work upward.
