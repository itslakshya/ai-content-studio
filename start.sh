#!/bin/bash
set -e

echo "=============================================="
echo "  🚀 AI Content Studio — Starting..."
echo "=============================================="

# Debug: show what env vars are set (keys only, not values)
echo "📋 Environment variables present:"
env | grep -E "^(GROQ|TAVILY|MASTER|DEVTO|BLUESKY|TELEGRAM|PEXELS|PORT|BACKEND|FAISS|KNOWLEDGE|SQLITE|ENVIRONMENT|GROQ_MODEL)=" | cut -d= -f1 | sort

# Set data paths
export FAISS_DB_PATH=${FAISS_DB_PATH:-./data/faissdb}
export KNOWLEDGE_BASE_PATH=${KNOWLEDGE_BASE_PATH:-./data/knowledge_base}
export SQLITE_DB_PATH=${SQLITE_DB_PATH:-./data/content_studio.db}
export BACKEND_URL="http://localhost:8000"

echo "📁 FAISS path: $FAISS_DB_PATH"
echo "📁 Knowledge base: $KNOWLEDGE_BASE_PATH"
echo "📁 SQLite: $SQLITE_DB_PATH"

# Create data dirs if they don't exist
mkdir -p "$FAISS_DB_PATH" "$KNOWLEDGE_BASE_PATH" "$(dirname $SQLITE_DB_PATH)"

# Determine working directory
if [ -d "/home/user/app" ]; then
    APP_DIR="/home/user/app"
elif [ -d "/app" ]; then
    APP_DIR="/app"
else
    APP_DIR="$(pwd)"
fi
echo "📂 App directory: $APP_DIR"
cd "$APP_DIR"

# ── Start FastAPI backend (background) ──────────────────────────────────────
echo "🔧 Starting FastAPI backend on port 8000..."
python -m uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info 2>&1 &

BACKEND_PID=$!
echo "   Backend PID: $BACKEND_PID"

# Wait for backend — check up to 120 seconds
echo "⏳ Waiting for backend to be ready..."
READY=false
for i in $(seq 1 60); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Backend ready after ${i}x2 seconds!"
        READY=true
        break
    fi
    echo "   Attempt $i/60..."
    sleep 2
done

if [ "$READY" = false ]; then
    echo "❌ Backend did not start in 120 seconds — check logs above"
    echo "   Backend process still running: $(kill -0 $BACKEND_PID 2>&1 && echo YES || echo NO)"
fi

# ── Start Streamlit (foreground, Render's $PORT) ────────────────────────────
PORT=${PORT:-8501}
echo "🎨 Starting Streamlit on port $PORT..."
exec streamlit run frontend/app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false \
    --theme.primaryColor "#7c6af7" \
    --theme.backgroundColor "#0e0e14" \
    --theme.secondaryBackgroundColor "#13131c" \
    --theme.textColor "#e2e2f0"