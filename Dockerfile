FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 user

WORKDIR /home/user/app

# ── Memory optimization for Render free tier (512MB) ─────────────────────────
# Install CPU-only PyTorch FIRST. The default torch installation includes
# CUDA libraries (~300MB RAM) that are useless on a CPU-only server.
# CPU-only torch uses ~150MB RAM instead — the difference between fitting
# in 512MB and crashing with OOM.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install remaining dependencies (sentence-transformers will reuse the
# already-installed CPU torch instead of pulling the full CUDA version)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Fix permissions BEFORE switching to non-root user
RUN mkdir -p /home/user/app/data/faissdb \
             /home/user/app/data/knowledge_base && \
    chown -R user:user /home/user/app && \
    chmod +x start.sh

USER user

EXPOSE 8501

# Reduce PyTorch memory further at runtime
ENV OMP_NUM_THREADS=1
ENV TOKENIZERS_PARALLELISM=false
ENV TRANSFORMERS_CACHE=/home/user/app/.cache

CMD ["./start.sh"]