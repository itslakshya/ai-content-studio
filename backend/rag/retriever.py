# backend/rag/retriever.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Dict, Any, Optional
import numpy as np
from rank_bm25 import BM25Okapi

from rag.vectorstore import get_vector_store, FAISSVectorStore
from config import get_settings


class BM25Retriever:
    """
    BM25 (Best Match 25) keyword-based retriever.

    INTERVIEW: "What is BM25 and how does it differ from TF-IDF?"
    ANSWER: "BM25 is an improved version of TF-IDF. TF-IDF grows unboundedly
    with term frequency. BM25 adds saturation (diminishing returns after
    several occurrences) and document length normalization. It's been the
    de-facto standard in search engines since the 1990s."
    """

    def __init__(self, corpus: List[str]):
        tokenized_corpus = [doc.lower().split() for doc in corpus]
        self.bm25 = BM25Okapi(tokenized_corpus)
        self.corpus = corpus

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        tokenized_query = query.lower().split()
        scores = self.bm25.get_scores(tokenized_query)
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append({
                    "text": self.corpus[idx],
                    "bm25_score": float(scores[idx]),
                    "corpus_index": int(idx),
                    "retrieval_method": "bm25",
                })
        return results


class HybridRetriever:
    """
    Three-layer hybrid retriever: FAISS + BM25 + FlashRank.

    Pipeline:
    1. FAISS retrieves top_k semantically similar chunks
    2. BM25 retrieves top_k keyword-matching chunks
    3. Results are merged and deduplicated
    4. FlashRank reranks the merged list by true relevance
    5. Top rerank_top_n results are returned to the Research Agent

    INTERVIEW: "How does your reranking step work?"
    ANSWER: "After dense and sparse retrieval, I have up to 2*top_k candidate
    chunks. FlashRank uses a cross-encoder that sees the query AND document
    together, giving much more accurate relevance scores than the bi-encoder
    used in initial retrieval. This two-stage approach (fast retrieval +
    accurate reranking) is the standard pattern in production RAG systems
    at companies like Notion and Perplexity."
    """

    def __init__(self, vector_store: Optional[FAISSVectorStore] = None):
        self.settings = get_settings()
        self.vector_store = vector_store or get_vector_store()
        self._bm25: Optional[BM25Retriever] = None
        self._ranker = None
        self._corpus_size = 0

    def _get_bm25(self) -> Optional[BM25Retriever]:
        """Lazily initialize BM25, rebuild if corpus grew."""
        all_texts = self.vector_store.get_all_texts()
        if not all_texts:
            return None
        if len(all_texts) != self._corpus_size:
            self._bm25 = BM25Retriever(all_texts)
            self._corpus_size = len(all_texts)
        return self._bm25

    def _get_ranker(self):
        """Lazily initialize FlashRank reranker."""
        if self._ranker is None:
            from flashrank import Ranker
            print("🔄 Loading FlashRank reranker...")
            self._ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")
            print("✅ FlashRank reranker loaded")
        return self._ranker

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        rerank_top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Full hybrid retrieval pipeline.

        Args:
            query: User's search query
            top_k: How many results to get from each retriever
            rerank_top_n: How many final results after reranking

        Returns:
            List of top reranked results with text, source, and scores
        """
        top_k = top_k or self.settings.top_k_retrieval
        rerank_top_n = rerank_top_n or self.settings.rerank_top_n

        if self.vector_store.total_chunks == 0:
            print("⚠️  No documents in vector store.")
            return []

        # ── LAYER 1: Dense Retrieval (FAISS) ─────────────────────────────────
        # Use a lower threshold for dense retrieval — let reranker filter
        dense_results = self.vector_store.search(
            query,
            top_k=top_k,
            score_threshold=0.0,   # Accept all FAISS results, reranker filters
        )
        print(f"   Dense retrieval: {len(dense_results)} results")

        # ── LAYER 2: Sparse Retrieval (BM25) ─────────────────────────────────
        bm25 = self._get_bm25()
        bm25_results = []
        if bm25:
            raw_bm25 = bm25.search(query, top_k=top_k)
            all_meta = [
                self.vector_store.get_metadata_by_index(i)
                for i in range(self.vector_store.total_chunks)
            ]
            for r in raw_bm25:
                idx = r["corpus_index"]
                if idx < len(all_meta) and all_meta[idx]:
                    bm25_results.append({
                        **all_meta[idx],
                        "bm25_score": r["bm25_score"],
                        "retrieval_method": "bm25",
                    })
        print(f"   BM25 retrieval:  {len(bm25_results)} results")

        # ── MERGE + DEDUPLICATE ───────────────────────────────────────────────
        seen = set()
        merged = []
        for result in dense_results + bm25_results:
            key = result.get("chunk_id", result.get("text", "")[:50])
            if key not in seen:
                seen.add(key)
                merged.append(result)

        print(f"   Merged (deduped): {len(merged)} unique results")

        if not merged:
            return []

        # ── LAYER 3: Reranking (FlashRank) ───────────────────────────────────
        try:
            from flashrank import RerankRequest
            ranker = self._get_ranker()

            # FlashRank newer versions return dicts, older return objects
            # We support both by checking the return type
            passages = [{"id": i, "text": r["text"]} for i, r in enumerate(merged)]
            rerank_request = RerankRequest(query=query, passages=passages)
            reranked_raw = ranker.rerank(rerank_request)

            final_results = []
            for item in reranked_raw[:rerank_top_n]:
                # Handle both dict and object return types from FlashRank
                if isinstance(item, dict):
                    item_id = item.get("id", item.get("index", 0))
                    item_score = item.get("score", item.get("relevance_score", 0.0))
                else:
                    item_id = getattr(item, "id", getattr(item, "index", 0))
                    item_score = getattr(item, "score", getattr(item, "relevance_score", 0.0))

                result = merged[item_id].copy()
                result["rerank_score"] = float(item_score)
                result["final_rank"] = len(final_results) + 1
                final_results.append(result)

            print(f"   After reranking: {len(final_results)} final results ✅")
            return final_results

        except Exception as e:
            print(f"⚠️  Reranking failed ({e}), using merged results")
            # Fallback: return merged sorted by FAISS score
            merged.sort(key=lambda x: x.get("score", 0), reverse=True)
            return merged[:rerank_top_n]

    def format_for_prompt(self, results: List[Dict[str, Any]]) -> str:
        """
        Format retrieval results into a clean context string for the LLM.

        INTERVIEW: "How do you pass retrieved context to the LLM?"
        ANSWER: "Retrieved chunks are formatted into a structured context
        block with source attribution and relevance scores. The prompt
        instructs the LLM to only use facts present in this context —
        this is the grounding mechanism that prevents hallucination."
        """
        if not results:
            return "No relevant documents found in knowledge base."

        parts = ["=== Retrieved Context ===\n"]
        for i, r in enumerate(results, 1):
            score = r.get("rerank_score", r.get("score", 0))
            parts.append(
                f"[Source {i}: {r.get('source', 'Unknown')} | Relevance: {score:.3f}]\n"
                f"{r.get('text', '')}\n"
            )
        parts.append("=== End of Retrieved Context ===")
        return "\n".join(parts)


# Singleton
_retriever_instance: Optional[HybridRetriever] = None


def get_retriever() -> HybridRetriever:
    """Returns the singleton hybrid retriever."""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = HybridRetriever()
    return _retriever_instance