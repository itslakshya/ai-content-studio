#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# AI Content Studio — Startup Script (Render.com)
# Launches FastAPI backend and Streamlit frontend
# (external $PORT, assigned by Render at runtime) in one container.
# ─────────────────────────────────────────────────────────────────────────────

set -e

echo "=============================================="
echo "  🚀 AI Content Studio — Starting..."
echo "=============================================="

# ── Render free tier has NO persistent disk ─────────────────────────────────
# The filesystem resets on every restart/redeploy. SQLite session history
# will reset, but the FAISS index rebuilds automatically from the
# data/knowledge_base/*.txt files (which ARE part of the repo, so nothing
# is lost there). This is an acceptable tradeoff for a portfolio demo.
# If you upgrade to a paid Render plan later, add a persistent disk mounted
# at /data and set SQLITE_DB_PATH=/data/content_studio.db /
# FAISS_DB_PATH=/data/faissdb to make history durable across restarts.
export FAISS_DB_PATH=${FAISS_DB_PATH:-./data/faissdb}
export KNOWLEDGE_BASE_PATH=${KNOWLEDGE_BASE_PATH:-./data/knowledge_base}
export SQLITE_DB_PATH=${SQLITE_DB_PATH:-./data/content_studio.db}

# ── BACKEND_URL for Streamlit to reach FastAPI (same container, localhost) ──
export BACKEND_URL="http://localhost:8000"

# ── Start FastAPI backend (background, internal port 8000) ──────────────────
echo "🔧 Starting FastAPI backend on internal port 8000..."
cd /home/user/app 2>/dev/null || cd /app
python -m uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info &

BACKEND_PID=$!
echo "   Backend PID: $BACKEND_PID"

# Wait for backend to be ready
echo "⏳ Waiting for backend..."
for i in $(seq 1 60); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Backend ready!"
        break
    fi
    sleep 2
done

# ── Start Streamlit frontend (foreground, Render's $PORT) ───────────────────
# Render sets $PORT automatically — default to 8501 for local docker testing.
PORT=${PORT:-8501}
echo "🎨 Starting Streamlit frontend on port $PORT..."
exec streamlit run frontend/app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false \
    --theme.primaryColor "#7c6af7" \
    --theme.backgroundColor "#0e0e14" \
    --theme.secondaryBackgroundColor "#13131c" \
    --theme.textColor "#e2e2f0"