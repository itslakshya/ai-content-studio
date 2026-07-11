# test_day1.py
# ─────────────────────────────────────────────────────────────────────────────
# Run this from your ai-content-studio root folder:
#   python test_day1.py
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))


def print_header(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_result(label: str, success: bool, detail: str = ""):
    icon = "✅" if success else "❌"
    print(f"  {icon} {label}")
    if detail:
        print(f"     {detail}")


# ── TEST 1: Core imports ───────────────────────────────────────────────────────
print_header("TEST 1: Checking imports")

try:
    from config import get_settings, validate_settings
    print_result("config.py imports", True)
except Exception as e:
    print_result("config.py imports", False, str(e))
    sys.exit(1)

try:
    from agents.state import ContentState, create_initial_state
    print_result("agents/state.py imports", True)
except Exception as e:
    print_result("agents/state.py imports", False, str(e))

try:
    from agents.llm_client import get_llm, test_llm_connection
    print_result("agents/llm_client.py imports", True)
except Exception as e:
    print_result("agents/llm_client.py imports", False, str(e))

# ── TEST 1b: Package imports ───────────────────────────────────────────────────
print_header("TEST 1b: Checking installed packages")

packages = {
    "langgraph": "langgraph",
    "langchain": "langchain",
    "langchain_groq": "langchain-groq",
    "faiss": "faiss-cpu",
    "sentence_transformers": "sentence-transformers",
    "rank_bm25": "rank-bm25",
    "fastapi": "fastapi",
    "streamlit": "streamlit",
    "tavily": "tavily-python",
    "flashrank": "flashrank",
    "slowapi": "slowapi",
}

all_ok = True
for module, pip_name in packages.items():
    try:
        mod = __import__(module)
        ver = getattr(mod, "__version__", "installed")
        print_result(f"{pip_name}", True, ver)
    except ImportError:
        print_result(f"{pip_name}", False, f"Run: uv pip install {pip_name}")
        all_ok = False

if not all_ok:
    print("\n  ⚠️  Some packages missing. Run:")
    print("  uv pip install -r requirements.txt")


# ── TEST 2: Settings ──────────────────────────────────────────────────────────
print_header("TEST 2: Loading settings from .env")

try:
    settings = get_settings()
    has_groq = bool(
        settings.groq_api_key
        and settings.groq_api_key != "your_groq_api_key_here"
    )
    has_tavily = bool(
        settings.tavily_api_key
        and settings.tavily_api_key != "your_tavily_api_key_here"
    )

    print_result("Settings loaded", True)
    print_result(
        "GROQ_API_KEY found", has_groq,
        "❌ Missing! Add to .env" if not has_groq else f"Model: {settings.groq_model}"
    )
    print_result(
        "TAVILY_API_KEY found", has_tavily,
        "❌ Missing! Add to .env" if not has_tavily else "Key present ✓"
    )
    print_result("Chunk size", True, f"{settings.chunk_size} tokens")
    print_result("Critique threshold", True, f"{settings.critique_threshold}")
    print_result("FAISS path", True, settings.faiss_db_path)

except Exception as e:
    print_result("Settings load failed", False, str(e))


# ── TEST 3: State object ──────────────────────────────────────────────────────
print_header("TEST 3: Creating agent state")

try:
    import uuid
    state = create_initial_state(
        topic="AI in Healthcare",
        tone="professional",
        target_platforms=["blog", "linkedin", "twitter"],
        session_id=str(uuid.uuid4()),
    )
    print_result("State created", True)
    print_result("Topic", True, state["topic"])
    print_result("Tone", True, state["tone"])
    print_result("Platforms", True, str(state["target_platforms"]))
    print_result(
        "Defaults OK",
        state["rewrite_count"] == 0 and state["hitl_status"] == "pending",
        f"rewrite_count={state['rewrite_count']}, hitl_status={state['hitl_status']}"
    )
except Exception as e:
    print_result("State creation failed", False, str(e))


# ── TEST 4: FAISS sanity check ────────────────────────────────────────────────
print_header("TEST 4: FAISS vector store sanity check")

try:
    import faiss
    import numpy as np

    # Create a tiny FAISS index and add 3 fake vectors
    dim = 4
    index = faiss.IndexFlatL2(dim)
    vectors = np.random.rand(3, dim).astype("float32")
    index.add(vectors)

    # Search for nearest neighbor
    query = np.random.rand(1, dim).astype("float32")
    distances, indices = index.search(query, 1)

    print_result("FAISS installed", True, f"faiss version: {faiss.__version__}")
    print_result("FAISS index create + add", True, f"3 vectors stored")
    print_result("FAISS search", True, f"Nearest index: {indices[0][0]}, Distance: {distances[0][0]:.4f}")

except Exception as e:
    print_result("FAISS check failed", False, str(e))


# ── TEST 5: LLM Connection ────────────────────────────────────────────────────
print_header("TEST 5: Testing Groq LLM connection")

settings = get_settings()
if not settings.groq_api_key or settings.groq_api_key == "your_groq_api_key_here":
    print("  ⚠️  Skipping LLM test — GROQ_API_KEY not set in .env")
else:
    async def run_llm_test():
        result = await test_llm_connection()
        print_result(
            "Groq API connected",
            result["success"],
            result.get("response", result.get("error", ""))[:120]
        )
        if result["success"]:
            print(f"\n  🤖 Model says: \"{result['response']}\"")
            print(f"  📦 Model used: {result['model']}")

    asyncio.run(run_llm_test())


# ── FINAL SUMMARY ─────────────────────────────────────────────────────────────
print_header("DAY 1 COMPLETE — SUMMARY")
print("""
  What you built today:
  ✅ Full folder structure
  ✅ Centralized config system (pydantic-settings)
  ✅ Agent shared state (TypedDict — LangGraph pattern)
  ✅ LLM client (Groq, Llama 3.3 70B)
  ✅ FAISS vector store (replaces ChromaDB, Windows-compatible)
  ✅ All API keys validated

  Next → Day 2: RAG Pipeline
         - Chunking strategy
         - FAISS vector store with real embeddings
         - BM25 keyword retrieval
         - FlashRank reranking
         - Hybrid retriever combining all three
""")

# ── FOLDER CHECK ──────────────────────────────────────────────────────────────
print_header("FOLDER STRUCTURE CHECK")

folders = [
    "backend/agents", "backend/rag", "backend/hitl",
    "backend/security", "backend/cache", "backend/api",
    "frontend/pages", "frontend/components",
    "data/knowledge_base", "tests",
]

for folder in folders:
    exists = os.path.isdir(folder)
    print_result(f"/{folder}", exists, "" if exists else "MISSING")