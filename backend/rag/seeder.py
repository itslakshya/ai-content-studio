# backend/rag/seeder.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from rag.vectorstore import get_vector_store
from rag.chunker import RecursiveChunker
from config import get_settings


async def seed_knowledge_base(force: bool = False) -> int:
    """
    Load all documents from knowledge_base/ into FAISS.

    Args:
        force: If True, re-seed even if index already has documents

    Returns:
        Number of chunks added (0 if already seeded)
    """
    settings = get_settings()
    store = get_vector_store()

    # Skip if already seeded
    if store.total_chunks > 0 and not force:
        print(f"📚 RAG knowledge base already seeded: {store.total_chunks} chunks")
        return 0

    kb_path = settings.get_knowledge_base_path()
    txt_files = list(kb_path.glob("*.txt"))

    if not txt_files:
        print(f"⚠️  No .txt files found in {kb_path}")
        print("   Add documents to data/knowledge_base/ to enable RAG")
        return 0

    print(f"🌱 Seeding RAG knowledge base from {len(txt_files)} documents...")
    chunker = RecursiveChunker()
    total_chunks = 0

    for filepath in txt_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                continue

            chunks = chunker.chunk_document(
                text=content,
                source=filepath.name,
                metadata={"file": filepath.name, "seeded_on_startup": True},
            )
            added = store.add_chunks(chunks)
            total_chunks += added
            print(f"   ✅ {filepath.name}: {added} chunks")

        except Exception as e:
            print(f"   ❌ Failed to load {filepath.name}: {e}")

    print(f"✅ RAG seeding complete: {total_chunks} total chunks indexed")
    return total_chunks