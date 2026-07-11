# backend/agents/llm_client.py


from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from functools import lru_cache
import sys
import os

# Add parent directory to path so we can import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_settings


@lru_cache()
def get_llm(temperature: float = 0.7) -> ChatGroq:
    """
    Returns a cached Groq LLM instance.

    temperature=0.0 → Deterministic (good for Critique Agent — needs consistency)
    temperature=0.7 → Creative (good for Format Agent — needs variety)
    temperature=0.3 → Balanced (good for Research + Rewrite Agents)

    INTERVIEW: "What does temperature do?"
    ANSWER: Controls randomness. 0 = always same answer. 1 = very creative/random.
    For factual tasks use low temp. For creative writing use higher.
    """
    settings = get_settings()

    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=temperature,
        max_tokens=4096,
        # Retry on rate limit or network errors
        max_retries=2,
    )


def get_critique_llm() -> ChatGroq:
    """Low temperature for consistent scoring."""
    return get_llm(temperature=0.0)


def get_creative_llm() -> ChatGroq:
    """Higher temperature for engaging content."""
    return get_llm(temperature=0.7)


def get_fast_llm() -> ChatGroq:
    """
    Fast, low-temperature LLM for utility tasks (visual concept extraction,
    topic disambiguation). Uses small max_tokens to minimize latency + cost.
    """
    settings = get_settings()
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.2,
        max_tokens=64,      # Short outputs only — keeps it fast & cheap
        max_retries=1,
    )


def get_balanced_llm() -> ChatGroq:
    """Balanced temperature for research and rewriting."""
    return get_llm(temperature=0.3)


async def test_llm_connection() -> dict:
    """
    Tests that the LLM connection works.
    Run this on Day 1 to confirm everything is set up correctly.
    Returns a dict with success status and response.
    """
    try:
        llm = get_llm()

        messages = [
            SystemMessage(content="You are a helpful assistant. Be brief."),
            HumanMessage(content="Say 'AI Content Studio is ready!' and nothing else.")
        ]

        response = await llm.ainvoke(messages)

        return {
            "success": True,
            "response": response.content,
            "model": get_settings().groq_model,
            "message": "✅ Groq LLM connected successfully!"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "❌ LLM connection failed. Check your GROQ_API_KEY in .env"
        }


def extract_tokens(response) -> tuple[int, int]:
    """
    Extract REAL token counts from a LangChain/Groq response.

    Groq returns usage in response.usage_metadata (LangChain standard) with:
      - input_tokens:  prompt tokens
      - output_tokens: completion tokens
      - total_tokens:  sum

    Returns: (input_tokens, output_tokens). Returns (0, 0) if unavailable.

    INTERVIEW: "How do you track token usage accurately?"
    ANSWER: "Groq's API returns actual token counts in usage_metadata via
    LangChain's standard interface. I extract input_tokens and output_tokens
    from every LLM response and accumulate them through the graph using
    LangGraph's operator.add reducer. This gives exact counts, not estimates —
    critical for accurate cost tracking at $0.59/1M tokens."
    """
    try:
        # LangChain standard: usage_metadata
        um = getattr(response, "usage_metadata", None)
        if um:
            return (
                um.get("input_tokens", 0) if isinstance(um, dict) else getattr(um, "input_tokens", 0),
                um.get("output_tokens", 0) if isinstance(um, dict) else getattr(um, "output_tokens", 0),
            )
        # Fallback: response_metadata.token_usage (older format)
        rm = getattr(response, "response_metadata", {})
        tu = rm.get("token_usage", {}) if isinstance(rm, dict) else {}
        if tu:
            return (tu.get("prompt_tokens", 0), tu.get("completion_tokens", 0))
    except Exception:
        pass
    return (0, 0)