import hashlib
import logging
import re
from functools import lru_cache

import requests
from flask import current_app


logger = logging.getLogger(__name__)


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


def _chunk(text, size=900, overlap=120):
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    return [text[start:start + size] for start in range(0, len(text), size - overlap)]


def _embed(text):
    response = requests.post(
        f"{current_app.config['OLLAMA_BASE_URL']}/api/embed",
        json={"model": current_app.config["EMBED_MODEL"], "input": text}, timeout=(5, 60),
    )
    response.raise_for_status()
    return response.json()["embeddings"][0]


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
                    ids=[doc["id"]], embeddings=[_embed(doc["text"])], documents=[doc["text"]],
                    metadatas=[{"source": doc["source"], "group": group}],
                )
        return True
    except Exception as exc:
        logger.warning("Vector index unavailable; lexical retrieval remains active: %s", exc)
        return False


def _lexical_retrieve(query, top_k):
    terms = set(re.findall(r"[a-z0-9_]{3,}", query.lower()))
    scored = []
    for doc in _documents():
        haystack = doc["text"].lower()
        score = sum(2 if term in doc["source"].lower() else 1 for term in terms if term in haystack)
        score += 0.01 * len(terms.intersection(set(re.findall(r"[a-z0-9_]{3,}", haystack))))
        scored.append((score, doc))
    return [doc for score, doc in sorted(scored, key=lambda item: item[0], reverse=True)[:top_k] if score > 0]


def retrieve(query, top_k=4):
    try:
        ensure_index()
        embedding = _embed(query)
        results = []
        per_collection = max(1, top_k // 2)
        for group in ("public", "sensitive"):
            data = _collection(group).query(query_embeddings=[embedding], n_results=per_collection, include=["documents", "metadatas", "distances"])
            for text, metadata, distance in zip(data["documents"][0], data["metadatas"][0], data["distances"][0]):
                results.append({"text": text, "source": metadata["source"], "group": group, "distance": distance})
        return sorted(results, key=lambda item: item["distance"])[:top_k]
    except Exception as exc:
        logger.warning("Using lexical RAG fallback: %s", exc)
        return _lexical_retrieve(query, top_k)
