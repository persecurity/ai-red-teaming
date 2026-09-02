import math
import logging
import re
from collections import Counter

import requests
from flask import current_app

from .observability import observation


logger = logging.getLogger(__name__)


_ROUTING_TERMS = {
    "airline", "airport", "bag", "baggage", "boarding", "booking", "cabin",
    "cancel", "cancellation", "cancellations", "checkin", "delay", "delays", "departure",
    "fare", "fares", "flight", "flights", "gate", "luggage", "mile", "miles", "passenger",
    "passengers", "pgairlines", "pilot", "pilots", "pnr", "policy", "rebook", "rebooking",
    "refund", "refunds", "roster", "ticket", "tickets", "travel", "wings",
}
_STOP_WORDS = {
    "about", "after", "also", "before", "could", "does", "from", "have", "into",
    "please", "should", "that", "their", "there", "these", "they", "this", "what",
    "when", "where", "which", "with", "would", "your",
}


def _token_list(text):
    """Return stable search tokens while treating hyphenated terms as one word."""
    return [
        token for token in re.findall(r"[a-z0-9]+", text.lower().replace("-", ""))
        if len(token) >= 3 and token not in _STOP_WORDS
    ]


def _tokens(text):
    return set(_token_list(text))


def _documents():
    root = current_app.config["CORPUS_PATH"]
    docs = []
    for group in ("public", "sensitive"):
        for path in sorted((root / group).glob("*")):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for index, chunk in enumerate(_chunk(text)):
                    docs.append({"id": f"{group}-{path.stem}-{index}", "group": group, "source": path.name, "text": chunk})
    return docs


def should_retrieve(query):
    """Route only PG-Airlines/company-document questions to the RAG pipeline."""
    normalized = re.sub(r"[^a-z0-9]+", "", query.lower())
    terms = _tokens(query)
    return "pgairlines" in normalized or bool(terms.intersection(_ROUTING_TERMS))


def _chunk(text, size=900, overlap=120):
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    return [text[start:start + size] for start in range(0, len(text), size - overlap)]


def _embed(text, observation_name="embed-query"):
    model = current_app.config["EMBED_MODEL"]
    with observation(
        observation_name,
        as_type="embedding",
        input=text,
        model=model,
        metadata={"provider": "ollama"},
    ) as embedding_observation:
        response = requests.post(
            f"{current_app.config['OLLAMA_BASE_URL']}/api/embed",
            json={"model": model, "input": text},
            timeout=(5, 60),
        )
        response.raise_for_status()
        payload = response.json()
        embedding = payload["embeddings"][0]
        embedding_observation.update(
            output={"dimensions": len(embedding)},
            model=payload.get("model", model),
            usage_details={"input": payload.get("prompt_eval_count", 0)},
            metadata={
                "provider": "ollama",
                "load_duration_ns": payload.get("load_duration", 0),
                "total_duration_ns": payload.get("total_duration", 0),
            },
        )
        return embedding


def _collection(group):
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(
        path=str(current_app.config["CHROMA_PATH"]),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(f"pg_airlines_{group}", metadata={"hnsw:space": "cosine"})


def ensure_index():
    docs = _documents()
    try:
        for group in ("public", "sensitive"):
            collection = _collection(group)
            existing = set(collection.get(include=[]).get("ids", []))
            pending = [doc for doc in docs if doc["group"] == group and doc["id"] not in existing]
            for doc in pending:
                collection.add(
                    ids=[doc["id"]],
                    embeddings=[_embed(doc["text"], "embed-document")],
                    documents=[doc["text"]],
                    metadatas=[{"source": doc["source"], "group": group}],
                )
        return True
    except Exception as exc:
        logger.warning("Vector index unavailable; lexical retrieval remains active: %s", exc)
        return False


def _bm25_scores(query, documents):
    """Calculate BM25 scores over the small local corpus, with a filename-title boost."""
    query_terms = _tokens(query)
    if not query_terms or not documents:
        return {doc["id"]: 0.0 for doc in documents}
    tokenized = {doc["id"]: _token_list(doc["text"]) for doc in documents}
    average_length = sum(len(tokens) for tokens in tokenized.values()) / len(documents)
    document_frequency = {
        term: sum(term in set(tokens) for tokens in tokenized.values()) for term in query_terms
    }
    scores = {}
    for doc in documents:
        tokens = tokenized[doc["id"]]
        frequencies = Counter(tokens)
        length_normalizer = 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(average_length, 1))
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if frequency:
                inverse_frequency = math.log(
                    1 + (len(documents) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
                )
                score += inverse_frequency * (frequency * 2.5) / (frequency + length_normalizer)
            if term in _tokens(doc["source"]):
                score += 0.75
        scores[doc["id"]] = score
    return scores


def _lexical_retrieve(query, top_k):
    documents = _documents()
    lexical_scores = _bm25_scores(query, documents)
    scored = []
    for doc in documents:
        score = lexical_scores[doc["id"]]
        normalized_score = score / (score + 1) if score else 0.0
        result = {**doc, "bm25_score": round(score, 4), "combined_score": round(normalized_score, 4)}
        scored.append((score, result))
    return [doc for score, doc in sorted(scored, key=lambda item: item[0], reverse=True)[:top_k] if score > 0]


def retrieve(query, top_k=4):
    with observation(
        "retrieve-context",
        as_type="retriever",
        input={"query": query, "top_k": top_k},
        metadata={"index": "pg-airlines", "strategy": "hybrid-vector-bm25"},
    ) as retriever:
        if not should_retrieve(query):
            retriever.update(output={"documents": [], "route": "not-applicable"})
            return []
        try:
            ensure_index()
            embedding = _embed(query)
            results = []
            lexical_scores = _bm25_scores(query, _documents())
            per_collection = max(1, top_k // 2)
            for group in ("public", "sensitive"):
                data = _collection(group).query(query_embeddings=[embedding], n_results=per_collection, include=["documents", "metadatas", "distances"])
                for chunk_id, text, metadata, distance in zip(
                    data["ids"][0], data["documents"][0], data["metadatas"][0], data["distances"][0]
                ):
                    vector_score = max(0.0, min(1.0, 1.0 - float(distance)))
                    if vector_score < current_app.config["RAG_MIN_VECTOR_SCORE"]:
                        continue
                    doc = {"id": chunk_id, "text": text, "source": metadata["source"], "group": group}
                    lexical_score = lexical_scores.get(chunk_id, 0.0)
                    normalized_lexical_score = lexical_score / (lexical_score + 1) if lexical_score else 0.0
                    combined_score = (0.8 * vector_score) + (0.2 * normalized_lexical_score)
                    results.append({
                        **doc,
                        "distance": round(float(distance), 4),
                        "vector_score": round(vector_score, 4),
                        "bm25_score": round(lexical_score, 4),
                        "combined_score": round(combined_score, 4),
                    })
            if results:
                selected = sorted(
                    results, key=lambda item: item["combined_score"], reverse=True
                )[:top_k]
                route = "hybrid"
            else:
                selected = _lexical_retrieve(query, top_k)
                route = "lexical-fallback"
            retriever.update(
                output={
                    "documents": [
                        {
                            "id": item.get("id"),
                            "source": item.get("source"),
                            "group": item.get("group"),
                            "vector_score": item.get("vector_score"),
                            "bm25_score": item.get("bm25_score"),
                            "combined_score": item.get("combined_score"),
                        }
                        for item in selected
                    ]
                },
                metadata={"route": route, "document_count": len(selected)},
            )
            return selected
        except Exception as exc:
            logger.warning("Using lexical RAG fallback: %s", exc)
            selected = _lexical_retrieve(query, top_k)
            retriever.update(
                output={
                    "documents": [
                        {
                            "id": item.get("id"),
                            "source": item.get("source"),
                            "group": item.get("group"),
                            "bm25_score": item.get("bm25_score"),
                            "combined_score": item.get("combined_score"),
                        }
                        for item in selected
                    ]
                },
                metadata={"route": "lexical-error-fallback", "error": str(exc)},
                level="WARNING",
            )
            return selected
