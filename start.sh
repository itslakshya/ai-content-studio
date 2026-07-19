#!/bin/bash


echo "=============================================="
echo "  AI Content Studio — Starting..."
echo "=============================================="

# ── Data paths ─────────────────────────────────────────────────────────────
export FAISS_DB_PATH=${FAISS_DB_PATH:-./data/faissdb}
export KNOWLEDGE_BASE_PATH=${KNOWLEDGE_BASE_PATH:-./data/knowledge_base}
export SQLITE_DB_PATH=${SQLITE_DB_PATH:-./data/content_studio.db}
export BACKEND_URL="http://localhost:8000"

mkdir -p data/faissdb data/knowledge_base

PORT=${PORT:-8501}
echo "Public port (Streamlit): $PORT"
echo "Internal port (FastAPI): 8000 (loopback only, not exposed)"
echo ""

# ── FastAPI: BACKGROUND, LOOPBACK-ONLY ─────────────────────────────────────
# Loopback binding is what prevents Render from seeing a second port.
echo "Starting FastAPI on 127.0.0.1:8000 (internal only)..."
python -m uvicorn backend.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --log-level warning &

FASTAPI_PID=$!
echo "  FastAPI PID: $FASTAPI_PID"
echo ""

# ── Streamlit: FOREGROUND, PUBLIC PORT ─────────────────────────────────────
# Foreground = the process Render monitors and protects. This is the ONLY
# externally visible port, so all browser traffic routes here correctly.
echo "Starting Streamlit on 0.0.0.0:$PORT (public)..."
exec streamlit run frontend/app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false \
    --browser.gatherUsageStats false