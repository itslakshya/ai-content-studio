# ─────────────────────────────────────────────────────────────────────────────
# AI Content Studio — Dockerfile for Render.com (free Docker hosting)
# Runs FastAPI  + Streamlit 
# in a single container. Render assigns $PORT dynamically at runtime.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user (HF Spaces requirement)
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# Copy requirements first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create persistent data directories
# On HF Spaces, /data/ is the persistent volume.
# We symlink our data dirs to /data/ so SQLite + FAISS survive restarts.
RUN mkdir -p /data/faissdb /data/knowledge_base && \
    chown -R user:user /data

# Copy knowledge base to persistent volume (first-run seeding)
RUN cp -n data/knowledge_base/*.txt /data/knowledge_base/ 2>/dev/null || true

# Startup script — runs both FastAPI and Streamlit
COPY start.sh .
RUN chmod +x start.sh

# Switch to non-root user
USER user

# Render assigns the external port dynamically via $PORT env var.
# EXPOSE is documentation only; start.sh binds to $PORT at runtime.
EXPOSE 8501

CMD ["./start.sh"]