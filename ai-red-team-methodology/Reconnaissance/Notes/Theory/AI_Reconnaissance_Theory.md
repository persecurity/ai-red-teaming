# AI Application Architecture – Reconnaissance & Enumeration Notes

Modern AI applications are **multi-layered systems**, not single monolithic models. Each layer exposes different information and therefore represents a separate **reconnaissance/enumeration surface**.

## AI Reconnaissance – Passive vs Active & Enumeration Taxonomy

AI reconnaissance can be divided into two complementary approaches:

```
AI Reconnaissance
      │
      ├── Passive Recon
      │     └── Observe public information
      │
      └── Active Recon
            └── Interact directly with target

```

Both approaches are useful. In practice, assessments typically start with **passive reconnaissance** and then move to **active validation**.

---

### 1. Passive Reconnaissance

Passive reconnaissance gathers information **without directly interacting with the target system**.

#### Common techniques

- HTTP header analysis of publicly exposed resources
- public API documentation review
- GitHub/GitLab repository analysis
- job posting analysis
- archived documentation or historical data
- public configuration and deployment clues

#### Advantages

- does not directly touch the target,
- avoids target-side request logging,
- no target-side rate limiting,
- historical information may be available,
- useful for building an initial architecture hypothesis.

#### Limitations

Information may be:

- outdated,
- incomplete,
- incorrect,
- based on development configurations,
- different from the current production runtime.

#### Mental model

```
Public Data
   │
   ├── Documentation
   ├── Source Repositories
   ├── Job Listings
   ├── Headers / Metadata
   └── Historical Archives
          │
          ▼
 Initial Target Profile

```

---

### 2. Active Reconnaissance

Active reconnaissance involves **direct interaction with the AI application** by sending controlled queries and analyzing responses to map AI architecture, capabilities, and potential weaknesses. This includes AI service discovery, model fingerprinting, and probing RAG pipelines to better understand how the system processes and retrieves information.

Typical goals are to determine how the system actually behaves at runtime.

#### Techniques

- behavioral model probing,
- model knowledge-cutoff testing,
- tool enumeration,
- RAG behavior analysis,
- chunk-boundary detection,
- malformed-request testing,
- permission-boundary testing,
- error-message analysis.

#### Advantages

Active reconnaissance provides **runtime truth**.

It can reveal:

- hidden functionality,
- actual model behavior,
- real permission boundaries,
- runtime configuration,
- active tools,
- current RAG behavior,
- backend implementation details.

#### Disadvantages

Active probes may:

- generate logs,
- trigger alerts,
- consume rate-limited resources,
- be detected by monitoring systems.

```
Crafted Request
      │
      ▼
AI Application
      │
      ▼
Observe
 ├── Response
 ├── Error
 ├── Timing
 ├── Tool behavior
 └── Permission behavior
      │
      ▼
Runtime Intelligence

```

---

### Passive + Active Recon Workflow

A practical assessment usually combines both methods.

```
Passive Recon
     │
     ▼
Build hypotheses
     │
     ▼
Identify likely technologies
     │
     ▼
Active Recon
     │
     ▼
Validate hypotheses
     │
     ▼
Discover runtime-specific behavior

```

#### Key principle

**Passive recon tells you what might exist.**

**Active recon tells you what actually exists and how it behaves.**

---

### Enumeration Taxonomy

Different layers of the AI application expose different information.

```
AI Target
   │
   ├── Model Layer
   ├── RAG Layer
   ├── Agent Layer
   └── Infrastructure Layer

```

---

### 3. Model Layer Enumeration

The model layer concerns the underlying LLM and its observable behavior.

#### Enumerable properties

##### Model identity

Potentially identifiable characteristics include:

- vendor,
- model family,
- model version.

##### Capability boundaries

Examples:

- context-window size,
- supported languages,
- reasoning capabilities,
- multimodal capabilities,
- task limitations.

##### Training-data characteristics

Possible clues include:

- knowledge cutoff,
- domain expertise,
- known training artifacts,
- familiarity with specific technologies or events.

##### Behavioral constraints

Examples:

- safety filters,
- refusal behavior,
- content policies,
- formatting patterns.

#### Recon techniques

- knowledge probing,
- capability testing,
- response pattern analysis.

```
Prompt
   │
   ▼
Model Response
   │
   ├── Knowledge clues
   ├── Capability clues
   ├── Formatting patterns
   └── Safety behavior
          │
          ▼
    Model Fingerprint

```

---

### 4. RAG Enumeration

RAG systems retrieve external information before generation.

#### Enumerable properties

Reconnaissance may reveal:

- embedding model,
- vector database technology,
- chunk size,
- chunk overlap,
- chunking strategy,
- retrieval thresholds,
- document sources.

#### Techniques

##### Chunk-boundary probing

Attempts to infer how documents were divided before embedding.

Possible findings:

```
Original document
      │
      ▼
 ┌───────────┐
 │ Chunk 1   │
 └───────────┘
       ↕ overlap
 ┌───────────┐
 │ Chunk 2   │
 └───────────┘
       ↕ overlap
 ┌───────────┐
 │ Chunk 3   │
 └───────────┘

```

##### Embedding similarity analysis

Observing what types of queries cause particular documents to be retrieved may reveal aspects of the retrieval system.

##### Source citation extraction

If the system exposes citations, metadata, filenames, URLs, or source identifiers, these may reveal the underlying knowledge base.

---

### 5. Agent Enumeration

Agent-based systems introduce additional attack and reconnaissance surfaces because agents may invoke tools.

#### Enumerable properties

- available tools,
- tool schemas,
- tool parameters,
- permission boundaries,
- orchestration logic,
- error-handling behavior.

#### Important techniques

##### MCP schema extraction

MCP may directly expose information such as:

```
Tool
 ├── Name
 ├── Description
 ├── Parameters
 ├── Parameter types
 └── Return type

```

This makes MCP especially useful for capability discovery.

##### Tool invocation testing

Used to determine:

- which tools can actually execute,
- required parameters,
- available operations,
- restrictions imposed by orchestration logic.

##### Permission-boundary probing

Tests whether:

```
Agent
  │
  ├── Can read?
  ├── Can write?
  ├── Can execute?
  ├── Can access external systems?
  └── What resources are restricted?

```

Errors themselves may disclose significant architectural information.

---

### 6. Infrastructure Layer Enumeration

The infrastructure layer combines traditional web reconnaissance with AI-specific details.

#### Enumerable properties

- API endpoints,
- backend services,
- rate limits,
- authentication mechanisms,
- server identities,
- error formats,
- routing architecture,
- inference infrastructure.

#### Techniques

- HTTP header analysis,
- endpoint enumeration,
- error-message mining,
- request/response comparison,
- malformed request analysis.

Example:

```
Client
   │
   ▼
API Gateway
   │
   ├── Headers
   ├── Rate limits
   ├── Error formats
   └── Routing clues
   │
   ▼
Backend / AI Services

```

---

### Recon Matrix

| Layer | What can be enumerated | Example techniques |
| --- | --- | --- |
| **Model**                                        | identity, capabilities, cutoff, safety behavior | knowledge probing, capability tests |
| **RAG**                                          | embeddings, vector DB, chunks, sources          | chunk probing, citation extraction  |
| **Agent**                                        | tools, schemas, permissions, orchestration      | MCP enumeration, tool testing       |
| **Infrastructure**                               | endpoints, servers, limits, errors              | headers, endpoint enumeration       |

---

### Key Takeaways

**Passive recon**

→ low visibility, good for initial intelligence, but potentially stale.

**Active recon**

→ reveals real runtime behavior, but interactions are observable and may trigger defenses.

The most effective workflow is:

```
PASSIVE
  ↓
Understand architecture
  ↓
Form hypotheses
  ↓
ACTIVE
  ↓
Validate assumptions
  ↓
Enumerate runtime behavior

```

For AI red teaming, reconnaissance should therefore be performed **layer by layer**, because the useful information is not limited to the model itself. RAG systems, agent tools, orchestration logic, APIs, and underlying infrastructure can all expose valuable information about the system's capabilities and trust boundaries.

## Typical AI Application Stack

```
User Interface
(Web / Mobile / API)
        │
        ▼
API Gateway
        │
        ▼
Orchestration Layer
        │
        ├── RAG Pipeline
        ├── Agent Tools / MCP
        └── External Integrations / A2A
        │
        ▼
Inference Server
        │
        ▼
Underlying Model

```

### 1. User Interface

Users interact with the system through:

- web applications,
- mobile applications,
- APIs.

This is the externally visible entry point into the AI system.

---

### 2. API Gateway

Responsible for:

- authentication,
- rate limiting,
- request routing,
- forwarding requests to backend services.

**Recon value:** HTTP responses and headers may reveal:

- reverse proxy / gateway software,
- caching infrastructure,
- upstream servers,
- backend implementation details.

---

### 3. Orchestration Layer

Controls how requests move through the AI application.

Common frameworks:

- **LangChain**
- **LangGraph**
- **CrewAI**
- **AutoGen**

Typical responsibilities:

- prompt construction,
- context-window management,
- multi-step reasoning,
- tool invocation,
- RAG integration,
- communication with inference servers.

**Recon value:** frameworks can sometimes be fingerprinted through:

- characteristic error messages,
- response behavior,
- request structure,
- framework-specific quirks.

Important: RAG, tools, and inference calls often exist **inside the orchestration code**, rather than as completely independent services.

---

### 4. Middle-Tier Components

#### RAG – Retrieval-Augmented Generation

RAG retrieves external information before the model generates its answer.

Typical flow:

```
User query
   │
   ▼
Retriever
   │
   ▼
Vector Database
   │
   ▼
Relevant Documents
   │
   ▼
Prompt + Retrieved Context
   │
   ▼
LLM

```

Possible enumeration targets include RAG-specific parameters and behavior, such as retrieval mechanisms and accessible knowledge sources.

---

#### Agent Tools

Agents may be able to interact with external functionality such as:

- databases,
- APIs,
- files,
- search systems,
- internal services.

A major protocol in this area is **MCP – Model Context Protocol**.

Agent tools introduce important **permission and capability boundaries** that can be examined during authorized testing.

---

#### External Integrations

AI systems can communicate with:

- databases,
- file systems,
- external APIs,
- other agents.

One relevant protocol is **A2A – Agent-to-Agent**, which is designed for communication and collaboration between AI agents.

---

### 5. Inference Server

The inference server runs the model and typically handles:

- tokenization,
- prompt processing,
- generation,
- response formatting.

Common implementations:

- **Ollama** – commonly used for local deployments.
- **vLLM** – commonly used for production/high-throughput inference.
- **TGI (Text Generation Inference)** – Hugging Face inference server.

**Recon value:** different inference servers may expose recognizable:

- API structures,
- endpoints,
- error messages,
- response formats,
- behavioral signatures.

---

### 6. Underlying Model

The lowest layer is the neural network generating the response.

Direct access to model weights is normally unavailable, but the model's identity or family may sometimes be inferred through **behavioral fingerprinting**.

Signals can include:

- knowledge cutoff,
- known training-data artifacts,
- capability limitations,
- formatting tendencies,
- response patterns,
- model-specific behavior.

---

## MCP – Model Context Protocol

MCP standardizes how AI applications **discover and invoke tools**.

It uses **JSON-RPC** for communication.

A particularly important characteristic is that MCP is **self-describing**: servers can expose schemas describing their capabilities.

Schemas may reveal:

```
Tool name
   │
   ├── Description
   ├── Parameters
   ├── Parameter types
   └── Return types

```

From a reconnaissance perspective, MCP discovery can reveal:

- what tools are available,
- what operations an agent can perform,
- accepted parameters,
- accessible resources/data,
- potential permission boundaries.

### Key point

**MCP is a high-value enumeration target because capability discovery is part of the protocol's design.**

---

## A2A – Agent-to-Agent

A2A enables AI agents to communicate and collaborate, including across organizational boundaries.

It supports:

- capability discovery,
- task delegation,
- inter-agent communication,
- result aggregation.

From a reconnaissance perspective, A2A endpoints may reveal:

- available agents,
- agent capabilities,
- supported tasks,
- relationships between agents,
- trust relationships between systems.

### Key point

Like MCP, **A2A is especially interesting for reconnaissance because it exposes information about system capabilities and relationships.**

---

## Reconnaissance Mental Model

When analyzing an AI application, think in layers rather than focusing only on the LLM:

```
Interface
   ↓
Gateway
   ↓
Orchestration
   ↓
RAG / Tools / Integrations
   ↓
Inference Server
   ↓
Model

```

For each layer, ask:

**What technology is running here? → What information does it expose? → What capabilities can be discovered? → Where are the trust and permission boundaries?**

The main takeaway is that **AI reconnaissance is application-stack reconnaissance**. The model itself is only one component; gateways, orchestration frameworks, RAG systems, tools, protocols, integrations, and inference servers may expose significantly more useful information during an authorized security assessment.
