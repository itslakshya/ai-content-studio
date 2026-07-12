#!/bin/bash
set -e

echo "=============================================="
echo "  AI Content Studio — Starting..."
echo "=============================================="

# Debug
echo "PORT=$PORT"
echo "ENVIRONMENT=${ENVIRONMENT:-not set}"
env | grep -E "^(GROQ|TAVILY|MASTER|DEVTO|BLUESKY|TELEGRAM|PEXELS|ENVIRONMENT|GROQ_MODEL)=" | cut -d= -f1 | sort

# Data paths
export FAISS_DB_PATH=${FAISS_DB_PATH:-./data/faissdb}
export KNOWLEDGE_BASE_PATH=${KNOWLEDGE_BASE_PATH:-./data/knowledge_base}
export SQLITE_DB_PATH=${SQLITE_DB_PATH:-./data/content_studio.db}
export BACKEND_URL="http://localhost:8000"

mkdir -p data/faissdb data/knowledge_base

# Start FastAPI (background)
echo "Starting FastAPI on port 8000..."
python -m uvicorn backend.main:app \
    --host 0.0.0.0 --port 8000 --workers 1 --log-level info &

# Wait for backend (up to 3 minutes for first-time model download)
echo "Waiting for backend..."
for i in $(seq 1 90); do
    if curl -sf http://localhost:8000/ > /dev/null 2>&1; then
        echo "Backend ready!"
        break
    fi
    if [ $((i % 10)) -eq 0 ]; then echo "  Still waiting... ($i/90)"; fi
    sleep 2
done

# Start Streamlit (foreground, Render's $PORT)
PORT=${PORT:-8501}
echo "Starting Streamlit on port $PORT..."
exec streamlit run frontend/app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false