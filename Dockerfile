FROM python:3.12-slim-bookworm AS base

LABEL org.opencontainers.image.title="FinTrace"
LABEL org.opencontainers.image.description="中文企业级批量费控审查 Agent"
LABEL org.opencontainers.image.source="https://github.com/your-org/fintrace"

WORKDIR /app

# ── System deps ────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ────────────────────────────────────────────────
COPY requirements.txt requirements-eval.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-eval.txt

# ── Application ────────────────────────────────────────────────
COPY . .
RUN python -c "from fintrace import run_batch; print('FinTrace import OK')"

EXPOSE 8509

# ── Default: Streamlit frontend ────────────────────────────────
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8509", "--server.address=0.0.0.0"]

# ── CLI entry point ────────────────────────────────────────────
FROM base AS cli
ENTRYPOINT ["python", "cli.py"]
