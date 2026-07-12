#!/bin/bash
set -e

echo "=============================================="
echo "  AI Content Studio — Starting..."
echo "=============================================="

# Data paths
export FAISS_DB_PATH=${FAISS_DB_PATH:-./data/faissdb}
export KNOWLEDGE_BASE_PATH=${KNOWLEDGE_BASE_PATH:-./data/knowledge_base}
export SQLITE_DB_PATH=${SQLITE_DB_PATH:-./data/content_studio.db}
export BACKEND_URL="http://localhost:8000"

mkdir -p data/faissdb data/knowledge_base

# ── Start Streamlit FIRST so Render sees a port immediately ─────────────────
# Render's port scanner times out after ~5 minutes. If FastAPI (which needs
# to download the embedding model ~30MB on first boot) starts first, the model
# download blocks everything and Render kills the container before Streamlit
# ever binds to $PORT. Starting Streamlit first means Render sees the port
# within seconds, marks the deploy as healthy, and FastAPI can take its time
# loading the model in the background.
PORT=${PORT:-8501}
echo "Starting Streamlit on port $PORT (Render needs this ASAP)..."
streamlit run frontend/app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false &

STREAMLIT_PID=$!
echo "Streamlit PID: $STREAMLIT_PID (port $PORT bound)"

# Give Streamlit 3 seconds to bind the port
sleep 3

# ── Start FastAPI backend (takes longer — model download on first boot) ─────
echo "Starting FastAPI on port 8000 (model download may take 1-2 min)..."
exec python -m uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info