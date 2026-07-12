FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 user

WORKDIR /home/user/app

# Install Python dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directories and fix ALL permissions BEFORE switching to user
RUN mkdir -p /home/user/app/data/faissdb \
             /home/user/app/data/knowledge_base && \
    chown -R user:user /home/user/app && \
    chmod +x start.sh

# Switch to non-root user
USER user

EXPOSE 8501

CMD ["./start.sh"]