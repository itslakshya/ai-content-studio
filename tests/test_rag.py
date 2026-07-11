# tests/test_rag.py
# Run: pytest tests/test_rag.py -v

import pytest
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from rag.chunker import RecursiveChunker, DocumentChunk
from rag.embeddings import embed_texts, embed_single, compute_similarity
from rag.vectorstore import FAISSVectorStore


# ── Chunker tests ─────────────────────────────────────────────────────────────
def test_chunker_basic():
    chunker = RecursiveChunker()
    text = "This is a test document. " * 100
    chunks = chunker.chunk_document(text, source="test.txt")
    assert len(chunks) > 0
    assert all(isinstance(c, DocumentChunk) for c in chunks)


def test_chunker_metadata():
    chunker = RecursiveChunker()
    chunks = chunker.chunk_document(
        "Sample text " * 50,
        source="myfile.txt",
        metadata={"author": "test"},
    )
    assert all(c.source == "myfile.txt" for c in chunks)
    assert all("author" in c.metadata for c in chunks)


def test_chunker_empty_text():
    chunker = RecursiveChunker()
    chunks = chunker.chunk_document("", source="empty.txt")
    assert chunks == []


def test_chunker_short_text():
    chunker = RecursiveChunker()
    chunks = chunker.chunk_document("Short text.", source="short.txt")
    assert len(chunks) == 1
    assert chunks[0].text == "Short text."


def test_chunker_token_count():
    chunker = RecursiveChunker()
    chunks = chunker.chunk_document("Hello world. " * 20, source="test.txt")
    assert all(c.token_count > 0 for c in chunks)


# ── Embedding tests ───────────────────────────────────────────────────────────
def test_embed_texts_shape():
    embeddings = embed_texts(["hello world", "test sentence"])
    assert embeddings.shape == (2, 384)
    assert embeddings.dtype == np.float32


def test_embed_single_shape():
    vec = embed_single("test query")
    assert vec.shape == (1, 384)


def test_semantic_similarity_ordering():
    texts = [
        "AI in healthcare",
        "Machine learning for medical diagnosis",
        "Cooking recipes and food",
    ]
    embeddings = embed_texts(texts)
    sim_related = compute_similarity(embeddings[0], embeddings[1])
    sim_unrelated = compute_similarity(embeddings[0], embeddings[2])
    assert sim_related > sim_unrelated


# ── Vector store tests ────────────────────────────────────────────────────────
def test_vectorstore_add_and_search():
    import shutil
    store = FAISSVectorStore(index_path="./data/test_pytest")
    store.reset()

    chunker = RecursiveChunker()
    chunks = chunker.chunk_document(
        "Artificial intelligence is transforming healthcare. "
        "Machine learning models detect diseases early. " * 10,
        source="test.txt",
    )
    added = store.add_chunks(chunks)
    assert added > 0

    results = store.search("AI healthcare", top_k=2, score_threshold=-1.0)
    assert len(results) > 0
    assert all("text" in r for r in results)
    assert all("score" in r for r in results)

    shutil.rmtree("./data/test_pytest", ignore_errors=True)


def test_vectorstore_empty_search():
    import shutil
    store = FAISSVectorStore(index_path="./data/test_empty")
    store.reset()
    results = store.search("any query")
    assert results == []
    shutil.rmtree("./data/test_empty", ignore_errors=True)