FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# Install dependencies (no PyTorch — fastembed uses ONNX, ~4x lighter)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /home/user/app/data/faissdb \
             /home/user/app/data/knowledge_base && \
    chown -R user:user /home/user/app && \
    chmod +x start.sh

USER user

# Memory optimizations for 512MB containers
ENV OMP_NUM_THREADS=1
ENV TOKENIZERS_PARALLELISM=false

EXPOSE 8501
CMD ["./start.sh"]