# AI Content Studio

**Deployed on Render.com** (free Docker hosting) — single container running both FastAPI backend and Streamlit frontend.

# ✨ AI Content Studio

**Multi-agent AI content generation with human-in-the-loop review and auto-publishing.**

Generate professional blog posts, LinkedIn posts, Twitter threads, Bluesky posts, and Telegram messages from a single topic — reviewed by you, published everywhere.

![Architecture](https://img.shields.io/badge/LangGraph-Multi--Agent-purple)
![RAG](https://img.shields.io/badge/RAG-Hybrid%20FAISS%2BBM25-blue)
![LLM](https://img.shields.io/badge/LLM-Llama%203.3%2070B-green)
![Publishing](https://img.shields.io/badge/Publishing-Dev.to%20%7C%20Bluesky%20%7C%20Telegram-orange)

---

## Architecture

```
User Topic → Guardrails (3-tier safety) → Supervisor Agent
                                              │
                                    Topic Refinement (LLM)
                                              │
                                    ┌─────────┴─────────┐
                                    │                     │
                              Tavily Web Search    Hybrid RAG Retrieval
                              (real-time data)     (FAISS + BM25 + FlashRank)
                                    │                     │
                                    └─────────┬───────────┘
                                              │
                                    Research Agent (LLM compilation)
                                              │
                                    Critique Agent (quality gate, temp=0)
                                         │         │
                                    score < 0.75   score ≥ 0.75
                                         │              │
                                    Rewrite Agent   Format Agent
                                    (loop back)     (5 LLM calls)
                                                        │
                                              ┌────┬────┬────┬────┐
                                              Blog  LI  Twitter  BS  TG
                                                        │
                                              HITL Review (approve/edit/reject)
                                                        │
                                              Auto-Publish (Dev.to, Bluesky, Telegram)
```

## Key Features

### 🤖 Multi-Agent Pipeline (LangGraph)
- **5 specialized agents**: Supervisor → Research → Critique ⇄ Rewrite → Format
- **State management** with `operator.add` reducers for token accumulation
- **Critique-Rewrite loop** with configurable quality threshold (0.75)
- Real token tracking from Groq's `usage_metadata` (not estimates)

### 🔍 Hybrid RAG (FAISS + BM25 + FlashRank)
- **Dense retrieval**: FAISS with all-MiniLM-L6-v2 (384-dim embeddings)
- **Sparse retrieval**: BM25 for exact keyword matching
- **Cross-encoder reranking**: FlashRank (ms-marco-MiniLM-L-12-v2) for precision
- **18 domain documents** covering AI/ML, fintech, healthcare, sports, pop culture, and more
- ~150 indexed chunks with 512-token chunking and 50-token overlap

### 🛡️ Safety & Guardrails
- **3-tier guardrail**: keyword blocklist → pattern heuristics → LLM intent classifier
- Ambiguous topic refinement (short/vague → specific researchable angle)
- Empty topic rejection

### 🖼️ AI Image Generation
- **Pollinations.ai** (Flux model) generates topic-specific images from LLM-crafted prompts
- Session-stable seeds (same image across generate → review → publish)
- Cover image cached in SQLite (survives restarts)
- Fallback chain: Pollinations → Pexels → Pixabay → Picsum

### 📊 Observability
- Real per-agent token tracking (research/critique/format breakdown)
- Per-run latency, cost estimation ($0.59/1M tokens)
- SQLite-persisted metrics (survive restarts)
- Orphaned run cleanup on startup

### 📝 Human-in-the-Loop (HITL)
- Approve, Edit & Approve, Reject, Re-open for editing
- Per-platform reject (reject Twitter without affecting Blog)
- Content preview with rendered formatting

### 🚀 Multi-Platform Publishing
- **Dev.to** — full blog with cover image + inline images
- **Bluesky** — AT Protocol, plain text, sentence-boundary truncation
- **Telegram** — Bot API with HTML formatting + image
- **Twitter/X** — copy-paste (free tier read-only)
- **LinkedIn** — copy-paste (API restricted)

### 💾 Database (SQLite + WAL)
- Repository Pattern (SessionRepository, PublishRepository, MetricsRepository)
- Schema migrations v1→v4 (automatic, idempotent)
- Thread-local connections for SQLite thread safety
- Semantic cache with tone-aware matching and reject-invalidation

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | LangGraph (StateGraph, conditional edges, cycles) |
| LLM | Groq Cloud — Llama 3.3 70B Versatile |
| Embeddings | all-MiniLM-L6-v2 (384-dim, local) |
| Vector Store | FAISS (IndexFlatIP, cosine similarity) |
| Sparse Retrieval | BM25 (rank-bm25) |
| Reranking | FlashRank (ms-marco-MiniLM-L-12-v2) |
| Web Search | Tavily API (real-time research) |
| Backend | FastAPI + Uvicorn |
| Frontend | Streamlit |
| Database | SQLite (WAL mode) |
| Image Generation | Pollinations.ai (Flux model) |
| Publishing | httpx (Dev.to, Bluesky AT Protocol, Telegram Bot API) |

## Local Development

```bash
# Clone and setup
git clone https://github.com/YOUR_USERNAME/ai-content-studio.git
cd ai-content-studio
python -m venv venv
source venv/bin/activate  # or .\venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API keys (Groq, Tavily, etc.)

# Run
uvicorn backend.main:app --port 8000  # Terminal 1
streamlit run frontend/app.py          # Terminal 2
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MASTER_API_KEY` | ✅ | API authentication key |
| `GROQ_API_KEY` | ✅ | Groq Cloud LLM access |
| `TAVILY_API_KEY` | ✅ | Web search for research |
| `DEVTO_API_KEY` | ✅ | Dev.to blog publishing |
| `BLUESKY_HANDLE` | ✅ | Bluesky account handle |
| `BLUESKY_APP_PASSWORD` | ✅ | Bluesky app password |
| `TELEGRAM_BOT_TOKEN` | ✅ | Telegram bot token |
| `TELEGRAM_CHANNEL_ID` | ✅ | Telegram channel (@name) |
| `PEXELS_API_KEY` | ✅ | Fallback stock images |
| `ENVIRONMENT` | ⬜ | `development` or `production` |

## Test Results

```
GROUP A — Frontend:       19/19 ✅
GROUP C — Database:        7/7  ✅
GROUP D — Cache:           4/4  ✅
GROUP E — Image:           5/5  ✅
GROUP F — Observability:   9/9  ✅
GROUP R — RAG:             7/7  ✅  (100% Recall@3)
GROUP B — Security:        4/4  ✅
GROUP G — Guardrails:      5/5  ✅
────────────────────────────────────
TOTAL:                    60/60 ✅
```

## Project Structure

```
ai-content-studio/
├── backend/
│   ├── agents/          # LangGraph nodes (supervisor, research, critique, rewrite, format)
│   ├── cache/           # Semantic cache (cosine similarity + tone-aware)
│   ├── database/        # SQLite + WAL + Repository Pattern + migrations
│   ├── hitl/            # Human-in-the-loop store (approve/reject/reopen)
│   ├── observability/   # Token tracking + per-agent metrics
│   ├── publishing/      # Platform publishers + guardrails + image generation
│   ├── rag/             # Chunker + embeddings + FAISS store + hybrid retriever
│   ├── security/        # API key auth + rate limiting
│   ├── config.py        # Pydantic settings from .env
│   └── main.py          # FastAPI app + endpoints
├── frontend/
│   ├── ui/              # Streamlit pages (generate, review, history, observability)
│   ├── components/      # API client
│   └── app.py           # Main Streamlit app
├── data/
│   ├── knowledge_base/  # 18 RAG documents (AI, fintech, sports, pop culture...)
│   └── faissdb/         # FAISS vector index (auto-generated)
├── Dockerfile           # HuggingFace Spaces deployment
├── start.sh             # Dual-server startup script
└── requirements.txt     # Pinned dependencies
```

## License

MIT

---

