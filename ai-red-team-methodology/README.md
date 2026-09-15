# AI Red-Team Methodology

A practical, evidence-driven methodology for assessing AI-enabled applications. The material is based on various resources, including TCM Security, PortSwigger Web Security Academy, and a wide range of articles and videos.

> Use these techniques only against systems you own or are explicitly authorized to test. The PG-Airlines examples operate on synthetic data in the deliberately vulnerable [local lab](../ai-red-team-labs/PG-Airlines/README.md) included in this repository.

## Repository map

```text
ai-red-team-methodology/
├── README.md
├── 01-reconnaissance/
│   ├── theory.md
│   ├── practical-guide.md
│   ├── Supplement_Detection-and-Evasion/
│   │   ├── detection-and-evasion-techniques.md
│   │   └── img/
│   └── templates/
│       ├── reconnaissance-template.md
│       └── pg-airlines-example.md
└── flashcards/
    └── ai-security-flashcards.csv
```

## 01-reconnaissance

This directory contains the first phase of the methodology: systematically discovering and mapping an AI application's attack surface before deeper security testing. It combines conceptual guidance on passive and active reconnaissance with practical commands for examining models, RAG pipelines, agents, APIs, and infrastructure. The templates provide a consistent way to record evidence, assumptions, reconstructed architecture, and findings; the PG-Airlines document demonstrates the process on the accompanying training lab.

The [detection and evasion supplement](01-reconnaissance/Supplement_Detection-and-Evasion/detection-and-evasion-techniques.md) uses PG-Airlines traces to explain guardrail decisions, RAG information exposure, and the limits of pattern-based detection.

## Flashcards and Anki

The flashcard CSV contains one question-and-answer pair per row and can be imported directly into Anki:

1. In Anki, select **File → Import** and choose `flashcards/ai-security-flashcards.csv`.
2. Use a comma as the field separator.
3. Map the first field to **Front** and the second field to **Back**.
4. Select the desired deck and complete the import.

The file intentionally has no header row, so every row is imported as a flashcard.

Additional assessment phases can follow the same numbered structure as the methodology grows.
