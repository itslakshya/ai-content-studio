# backend/agents/research_agent.py

import sys, os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from tavily import TavilyClient
from tenacity import retry, stop_after_attempt, wait_exponential

from agents.state import ContentState
from agents.llm_client import get_balanced_llm, extract_tokens
from rag.retriever import get_retriever
from config import get_settings


def _search_web(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search the web using Tavily API.

    Tavily is purpose-built for AI agents — it returns clean,
    structured results without HTML/ads, unlike raw Google results.

    INTERVIEW: "Why Tavily over SerpAPI or Google Search API?"
    ANSWER: "Tavily is designed specifically for LLM agents. It returns
    clean extracted content (not raw HTML), has a generous free tier,
    and provides relevance scores per result. SerpAPI returns raw HTML
    you'd need to parse. For an agent that needs to read search results,
    Tavily is the right tool."
    """
    settings = get_settings()
    try:
        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",     # Deep search vs basic
            include_answer=True,          # Get Tavily's AI summary too
            include_raw_content=False,    # Skip raw HTML
        )
        return response.get("results", [])
    except Exception as e:
        print(f"   ⚠️  Tavily search failed for '{query}': {e}")
        return []


def _format_web_results(results: List[Dict[str, Any]]) -> tuple[str, List[str]]:
    """
    Convert raw Tavily results into clean text + source list.

    Returns:
        (formatted_text, list_of_source_urls)
    """
    if not results:
        return "", []

    parts = []
    sources = []

    for i, result in enumerate(results, 1):
        title = result.get("title", "Unknown")
        content = result.get("content", "")
        url = result.get("url", "")
        score = result.get("score", 0)

        if content:
            parts.append(
                f"[Web Source {i}: {title} | Score: {score:.2f}]\n"
                f"URL: {url}\n"
                f"{content[:800]}\n"  # Cap at 800 chars per result
            )
            if url:
                sources.append(url)

    return "\n".join(parts), sources


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def _compile_research(
    topic: str,
    tone: str,
    web_context: str,
    rag_context: str,
    sources: List[str],
) -> str:
    """
    Use the LLM to compile web + RAG findings into a structured research brief.

    Why compile instead of just concatenating?
    Raw search results are noisy — repetitive, off-topic, poorly structured.
    The LLM acts as an "editor" that pulls out the key facts, statistics,
    and insights relevant to the topic and target tone.

    INTERVIEW: "What is the Research Agent's actual job?"
    ANSWER: "It's not just a search wrapper. It searches, retrieves, then
    uses an LLM to synthesize the raw findings into a structured research
    brief — key facts, statistics, examples, controversies. This brief
    is what the Critique Agent evaluates and what the Format Agent writes
    from. The synthesis step is critical — raw search results would
    produce incoherent content if passed directly to the formatter."
    """
    llm = get_balanced_llm()

    system_prompt = """You are an expert research analyst. Your job is to compile 
research findings into a clear, factual brief that a content writer can use.

RULES:
1. Only include facts that appear in the provided sources
2. Always note which source a fact comes from (Web Source N or RAG)
3. Include specific statistics, numbers, and dates when available
4. Flag any contradictions between sources
5. Keep the brief focused and relevant to the topic
6. Do NOT add facts from your training data — only use provided sources
7. Structure the brief clearly with sections"""

    user_prompt = f"""
TOPIC: {topic}
TARGET TONE: {tone}

=== WEB SEARCH RESULTS ===
{web_context if web_context else "No web results available"}

=== KNOWLEDGE BASE (RAG) RESULTS ===  
{rag_context if rag_context else "No RAG results available"}

=== YOUR TASK ===
Compile a structured research brief with these sections:
1. KEY FACTS (bullet points, source-attributed)
2. STATISTICS & DATA (numbers, percentages, dates)
3. REAL-WORLD EXAMPLES (specific companies, products, use cases)
4. KEY CHALLENGES (problems this topic addresses)
5. TRENDING ANGLES (what's most discussed right now)

Be specific. Use exact numbers when available. Note sources.
Brief should be 400-600 words."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    response = await llm.ainvoke(messages)
    in_tok, out_tok = extract_tokens(response)
    return response.content, in_tok, out_tok


async def research_node(state: ContentState) -> dict:
    """
    Research Agent node — called by LangGraph.

    Pipeline:
    1. Run web search (Tavily) on topic + prepared queries
    2. Run RAG retrieval (HybridRetriever) 
    3. Compile findings into a structured research brief via LLM
    4. Return updated state fields

    INTERVIEW: "How did you ground your agents in real facts?"
    ANSWER: "The Research Agent runs two parallel lookups before any
    content is written: Tavily web search for current information and
    hybrid RAG retrieval from our knowledge base. An LLM then synthesizes
    these into a structured brief, explicitly instructed to only use
    provided sources. This brief is what the Critique Agent evaluates
    against — it scores how well the final content matches the brief."
    """
    settings = get_settings()
    topic = state["topic"]
    tone = state["tone"]

    print(f"\n{'='*50}")
    print(f"🔍 RESEARCH AGENT starting")
    print(f"   Topic: {topic}")
    print(f"{'='*50}")

    all_web_results = []
    all_sources = []

    # ── Step 1: Web Search (Tavily) ───────────────────────────────────────────
    # Use up to 2 of the supervisor's prepared queries to stay within rate limits
    queries_to_run = state.get("search_queries_used", [topic])[:2]

    print(f"   🌐 Running {len(queries_to_run)} web searches...")
    for query in queries_to_run:
        results = _search_web(query, max_results=settings.max_search_results)
        all_web_results.extend(results)
        print(f"      '{query}' → {len(results)} results")

    web_context, web_sources = _format_web_results(all_web_results)
    all_sources.extend(web_sources)
    print(f"   ✅ Web search: {len(all_web_results)} total results")

    # ── Step 2: RAG Retrieval (HybridRetriever) ───────────────────────────────
    print(f"   📚 Running RAG retrieval...")
    try:
        retriever = get_retriever()
        rag_results = retriever.retrieve(topic, top_k=5, rerank_top_n=3)
        rag_context = retriever.format_for_prompt(rag_results)

        # Add RAG sources
        rag_sources = list({r.get("source", "") for r in rag_results if r.get("source")})
        all_sources.extend(rag_sources)
        print(f"   ✅ RAG retrieval: {len(rag_results)} chunks retrieved")
    except Exception as e:
        print(f"   ⚠️  RAG retrieval failed: {e}")
        rag_context = ""

    # ── Step 3: Compile Research Brief ───────────────────────────────────────
    print(f"   🧠 Compiling research brief with LLM...")
    _agent_start = time.time()
    _in_tok, _out_tok = 0, 0
    try:
        research_brief, _in_tok, _out_tok = await _compile_research(
            topic=topic,
            tone=tone,
            web_context=web_context,
            rag_context=rag_context,
            sources=all_sources,
        )
        print(f"   ✅ Research brief: {len(research_brief)} chars "
              f"({_in_tok}+{_out_tok} tokens)")
    except Exception as e:
        print(f"   ❌ Research compilation failed: {e}")
        # Fallback: use raw web context if LLM compilation fails
        research_brief = web_context or rag_context or f"Research on {topic} (retrieval failed)"
    _agent_latency_ms = (time.time() - _agent_start) * 1000

    print(f"✅ Research Agent complete — {len(all_sources)} sources gathered")

    return {
        "research_data": research_brief,
        "sources": list(set(all_sources)),  # Deduplicate
        "current_agent": "critique",
        "total_input_tokens": _in_tok,
        "total_output_tokens": _out_tok,
        "agent_metrics": [{
            "agent": "research",
            "latency_ms": _agent_latency_ms,
            "input_tokens": _in_tok,
            "output_tokens": _out_tok,
        }],
        "messages": [
            AIMessage(content=f"Research complete. Brief: {len(research_brief)} chars, "
                             f"Sources: {len(all_sources)}")
        ],
    }