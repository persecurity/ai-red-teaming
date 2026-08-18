FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /lab
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x scripts/app-entrypoint.sh scripts/ollama-init.sh && mkdir -p data chroma
EXPOSE 5000
ENTRYPOINT ["./scripts/app-entrypoint.sh"]

