#!/bin/bash
echo "=============================================="
echo "  AI Content Studio — Starting..."
echo "=============================================="

export FAISS_DB_PATH=${FAISS_DB_PATH:-./data/faissdb}
export KNOWLEDGE_BASE_PATH=${KNOWLEDGE_BASE_PATH:-./data/knowledge_base}
export SQLITE_DB_PATH=${SQLITE_DB_PATH:-./data/content_studio.db}
export BACKEND_URL="http://localhost:8000"
mkdir -p data/faissdb data/knowledge_base

PORT=${PORT:-8501}

# ── FastAPI BACKGROUND (can take 60s to load model — that's OK) ─────────────
python -m uvicorn backend.main:app \
    --host 0.0.0.0 --port 8000 --workers 1 --log-level info &

# ── Streamlit FOREGROUND (Render monitors THIS process) ─────────────────────
# Streamlit MUST be foreground. When it's backgrounded, the OS kills it first
# under memory pressure → websocket drops → "Connection error 404" popup.
# As foreground, it's the primary process Render protects.
streamlit run frontend/app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false