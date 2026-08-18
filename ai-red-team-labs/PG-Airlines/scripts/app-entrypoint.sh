#!/bin/sh
set -eu
python -c 'import os,time,requests
url=os.getenv("OLLAMA_BASE_URL","http://ollama:11434").rstrip("/")+"/api/tags"
for attempt in range(90):
    try:
        if requests.get(url,timeout=3).ok: break
    except requests.RequestException: pass
    time.sleep(2)
else: raise SystemExit("Ollama did not become healthy")'
exec gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 240 wsgi:app

