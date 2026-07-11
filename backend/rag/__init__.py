# backend/rag/__init__.py
from .chunker import RecursiveChunker, DocumentChunk
from .embeddings import embed_texts, embed_single, compute_similarity
from .vectorstore import FAISSVectorStore, get_vector_store
from .retriever import HybridRetriever, get_retriever