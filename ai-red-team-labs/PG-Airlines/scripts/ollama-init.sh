#!/bin/sh
set -eu
export OLLAMA_HOST="${OLLAMA_BASE_URL:-http://ollama:11434}"
until ollama list >/dev/null 2>&1; do sleep 2; done
for model in "${CHAT_MODEL:-qwen3:8b}" "${CONFIGURED_JUDGE_MODEL:-qwen3:8b}" "${LLAMA_GUARD_MODEL:-llama-guard3:1b}" "${EMBED_MODEL:-nomic-embed-text}"; do
  ollama pull "$model"
done

