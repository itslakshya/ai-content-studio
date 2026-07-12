# backend/rag/embeddings.py


import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List
import numpy as np
from functools import lru_cache


EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384


@lru_cache(maxsize=1)
def get_embedding_model():
    """
    Load and cache the fastembed model.
    First call: ~2-3 seconds (downloads ONNX model ~30MB)
    Every subsequent call: instant (returns cached model)
    """
    print(f"🔄 Loading embedding model: {EMBEDDING_MODEL}")
    print("   (First load takes ~10 seconds — model downloads/initializes)")

    from fastembed import TextEmbedding
    model = TextEmbedding(model_name=EMBEDDING_MODEL)

    print(f"✅ Embedding model loaded — dimension: {EMBEDDING_DIMENSION}")
    return model


def embed_texts(texts: List[str], batch_size: int = 32) -> np.ndarray:
    """
    Convert a list of text strings into embedding vectors.
    Returns: numpy array of shape (len(texts), 384)
    """
    if not texts:
        return np.array([])

    model = get_embedding_model()

    # fastembed returns a generator — convert to numpy array
    embeddings = list(model.embed(texts, batch_size=batch_size))
    result = np.array(embeddings, dtype="float32")

    # L2 normalize (fastembed may already do this, but belt-and-suspenders)
    norms = np.linalg.norm(result, axis=1, keepdims=True)
    norms[norms == 0] = 1  # avoid division by zero
    result = result / norms

    return result


def embed_single(text: str) -> np.ndarray:
    """
    Embed a single text string. Used for query embedding at search time.
    Returns: numpy array of shape (1, 384)
    """
    embedding = embed_texts([text])
    return embedding.reshape(1, -1)


def compute_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """
    Compute cosine similarity between two vectors.
    For normalized vectors: similarity = dot product.
    """
    v1 = vec1.flatten()
    v2 = vec2.flatten()
    similarity = float(np.dot(v1, v2))
    return max(-1.0, min(1.0, similarity))