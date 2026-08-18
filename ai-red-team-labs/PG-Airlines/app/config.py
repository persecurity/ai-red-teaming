import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def security_level(value=None):
    try:
        level = int(value if value is not None else os.getenv("SECURITY_LEVEL", "1"))
    except (TypeError, ValueError):
        level = 1
    return min(5, max(1, level))


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "local-training-only-change-me")
    SECURITY_LEVEL = security_level()
    CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen3:8b")
    JUDGE_MODEL = os.getenv("CONFIGURED_JUDGE_MODEL", CHAT_MODEL)
    GUARD_MODEL = os.getenv("LLAMA_GUARD_MODEL", "llama-guard3:1b")
    EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
    OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
    SCAN_UPLOADS_WITH_GUARD = env_bool("SCAN_UPLOADS_WITH_GUARD", False)
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "5")) * 1024 * 1024
    DATABASE = Path(os.getenv("DATABASE_PATH", BASE_DIR / "data" / "lab.db"))
    CHROMA_PATH = Path(os.getenv("CHROMA_PATH", BASE_DIR / "chroma"))
    CORPUS_PATH = BASE_DIR / "rag_corpus"
    TESTING = False

