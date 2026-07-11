# backend/rag/vectorstore.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle
from typing import List, Dict, Any, Optional
from pathlib import Path
import numpy as np
import faiss

from rag.chunker import DocumentChunk
from rag.embeddings import embed_texts, embed_single, EMBEDDING_DIMENSION
from config import get_settings


class FAISSVectorStore:
    """
    FAISS-based vector store with persistence.

    Stores:
    - FAISS index (vectors)    → .faiss file
    - Metadata (text + source) → .pkl file

    INTERVIEW: "How does vector similarity search work?"
    ANSWER: "Each chunk is converted to a 384-dim vector by the embedding
    model. At search time, the query is also embedded. FAISS computes
    inner product (cosine similarity on L2-normalized vectors) between
    the query vector and all stored vectors, returning the top-k closest.
    The parallel metadata list maps each vector's position back to its
    original text and source document."
    """

    def __init__(self, index_path: Optional[str] = None):
        self.settings = get_settings()
        self.index_path = Path(index_path or self.settings.faiss_db_path)
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.faiss_file = self.index_path / "index.faiss"
        self.metadata_file = self.index_path / "metadata.pkl"

        # IndexFlatIP = exact inner product search
        # On L2-normalized vectors: inner product == cosine similarity
        self.index: faiss.IndexFlatIP = faiss.IndexFlatIP(EMBEDDING_DIMENSION)
        self.metadata: List[Dict[str, Any]] = []

        self._load_if_exists()

    def add_chunks(self, chunks: List[DocumentChunk]) -> int:
        """Embed and add document chunks to the FAISS index."""
        if not chunks:
            return 0

        print(f"🔄 Embedding {len(chunks)} chunks...")
        texts = [chunk.text for chunk in chunks]
        embeddings = embed_texts(texts)

        if len(embeddings) == 0:
            return 0

        self.index.add(embeddings)

        for chunk in chunks:
            self.metadata.append({
                "text": chunk.text,
                "chunk_id": chunk.chunk_id,
                "source": chunk.source,
                "chunk_index": chunk.chunk_index,
                "total_chunks": chunk.total_chunks,
                "token_count": chunk.token_count,
                "metadata": chunk.metadata,
            })

        self._save()
        print(f"✅ Added {len(chunks)} chunks | Total in index: {self.index.ntotal}")
        return len(chunks)

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for most similar chunks to a query string.

        IMPORTANT: IndexFlatIP returns cosine similarity in range [-1, 1].
        Default score_threshold is -1.0 (accept everything from FAISS).
        Quality filtering is handled downstream by FlashRank reranker.

        Args:
            query: Natural language search query
            top_k: Number of results to return
            score_threshold: Minimum cosine similarity (-1.0 to 1.0)
                             Default -1.0 = return all results unfiltered

        Returns:
            List of result dicts with text, source, score, metadata
        """
        if self.index.ntotal == 0:
            print("⚠️  Vector store is empty. Add documents first.")
            return []

        top_k = top_k or self.settings.top_k_retrieval

        # KEY FIX: Default to -1.0 (accept all FAISS results).
        # The 0.3 threshold in .env is for external callers who want
        # pre-filtered results. Internal retriever uses -1.0 and lets
        # FlashRank do the filtering.
        if score_threshold is None:
            score_threshold = -1.0

        # Embed the query
        query_vector = embed_single(query)

        # FAISS search
        actual_top_k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query_vector, actual_top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:  # FAISS returns -1 for invalid slots
                continue
            if float(score) < score_threshold:
                continue

            results.append({
                **self.metadata[idx],
                "score": float(score),
                "rank": len(results) + 1,
            })

        return results

    def get_all_texts(self) -> List[str]:
        """Return all stored chunk texts. Used by BM25 retriever."""
        return [m["text"] for m in self.metadata]

    def get_metadata_by_index(self, idx: int) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific FAISS index position."""
        if 0 <= idx < len(self.metadata):
            return self.metadata[idx]
        return None

    @property
    def total_chunks(self) -> int:
        return self.index.ntotal

    def _save(self):
        """Persist FAISS index and metadata to disk."""
        faiss.write_index(self.index, str(self.faiss_file))
        with open(self.metadata_file, "wb") as f:
            pickle.dump(self.metadata, f)

    def _load_if_exists(self):
        """Load existing index from disk if available."""
        if self.faiss_file.exists() and self.metadata_file.exists():
            print(f"📂 Loading existing FAISS index from {self.index_path}")
            self.index = faiss.read_index(str(self.faiss_file))
            with open(self.metadata_file, "rb") as f:
                self.metadata = pickle.load(f)
            print(f"✅ Loaded {self.index.ntotal} vectors from disk")

    def reset(self):
        """Clear the entire index."""
        self.index = faiss.IndexFlatIP(EMBEDDING_DIMENSION)
        self.metadata = []
        if self.faiss_file.exists():
            self.faiss_file.unlink()
        if self.metadata_file.exists():
            self.metadata_file.unlink()
        print("🗑️  Vector store reset")


_vector_store_instance: Optional[FAISSVectorStore] = None


def get_vector_store() -> FAISSVectorStore:
    """Returns the singleton vector store instance."""
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = FAISSVectorStore()
    return _vector_store_instance