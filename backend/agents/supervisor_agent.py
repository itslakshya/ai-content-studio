# backend/agents/supervisor_agent.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from langchain_core.messages import SystemMessage, HumanMessage
from agents.state import ContentState
from agents.llm_client import get_balanced_llm
from config import get_settings


def _refine_ambiguous_topic(topic: str) -> str:
    """
    Detect vague/ambiguous topics and expand them into clear, content-ready angles.

    Ambiguity signals: very short (< 4 words), no clear domain, abstract phrasing.
    Example: "AI becoming corrupt" → "How AI systems can be compromised: bias,
             data poisoning, and adversarial attacks in modern ML"

    INTERVIEW: "How do you handle vague user input?"
    ANSWER: "Short or abstract topics produce generic content because there's
    no angle to research. So the Supervisor detects ambiguity — fewer than 4
    meaningful words, no concrete domain — and uses a fast LLM call to expand
    the topic into a specific, researchable angle. This is a lightweight
    query-rewriting step, the same technique search engines use to disambiguate
    queries before retrieval."
    """
    words = [w for w in topic.split() if len(w) > 2]

    # Only refine if topic is short/potentially ambiguous
    if len(words) >= 5:
        return topic  # Already specific enough

    try:
        from agents.llm_client import get_fast_llm
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = get_fast_llm()
        r = llm.invoke([
            SystemMessage(content=(
                "You expand vague article topics into specific, clear angles for "
                "content creation. Keep the user's intent but add specificity. "
                "Output ONE clear topic line, max 14 words, no preamble. "
                "Examples:\n"
                "'AI becoming corrupt' -> 'How AI systems get compromised: bias, "
                "data poisoning, and adversarial attacks'\n"
                "'remote work' -> 'How remote work is reshaping company culture and "
                "productivity in 2025'\n"
                "'crypto' -> 'The state of cryptocurrency: adoption, regulation, and "
                "what comes next'"
            )),
            HumanMessage(content=f"Vague topic: {topic}\nSpecific angle:"),
        ])
        refined = r.content.strip().strip('"').strip()
        # Sanity check — must be reasonable length and not empty
        if refined and 5 < len(refined) < 120:
            print(f"   🔍 Topic refined: '{topic}' → '{refined}'")
            return refined
    except Exception as e:
        print(f"   ⚠️  Topic refinement skipped: {e}")

    return topic


def supervisor_node(state: ContentState) -> dict:
    """
    Supervisor Agent — validates input and initializes the pipeline.

    This is the FIRST node in the LangGraph graph.
    It receives the raw user request and prepares the state
    for the Research Agent.

    Returns:
        Partial state update — only the fields this agent modifies.
        LangGraph merges this back into the full state.

    INTERVIEW: "What does a LangGraph node return?"
    ANSWER: "A node returns a dict containing ONLY the fields it updated.
    LangGraph uses reducer functions to merge this partial update back
    into the full shared state. This is more efficient than passing and
    returning the entire state — only changes travel between nodes."
    """
    settings = get_settings()

    print(f"\n{'='*50}")
    print(f"🎯 SUPERVISOR AGENT starting")
    print(f"   Topic    : {state['topic']}")
    print(f"   Tone     : {state['tone']}")
    print(f"   Platforms: {state['target_platforms']}")
    print(f"{'='*50}")

    # ── Input Validation ──────────────────────────────────────────────────────
    errors = []

    if not state.get("topic") or len(state["topic"].strip()) < 3:
        errors.append("Topic must be at least 3 characters")

    if not state.get("tone"):
        errors.append("Tone is required")

    valid_tones = ["professional", "casual", "witty", "educational",
                   "inspirational", "conversational"]
    if state.get("tone") and state["tone"].lower() not in valid_tones:
        # Don't reject — just normalize to closest valid tone
        state = dict(state)
        state["tone"] = "professional"
        print(f"   ⚠️  Unknown tone, defaulting to 'professional'")

    if errors:
        return {
            "error": " | ".join(errors),
            "current_agent": "supervisor",
            "hitl_status": "error",
        }

    # ── Refine ambiguous topics into clear, researchable angles ───────────────
    topic = _refine_ambiguous_topic(state["topic"].strip())
    tone = state["tone"].lower()

    search_queries = [
        topic,
        f"{topic} latest developments 2024 2025",
        f"{topic} statistics data research",
        f"{topic} use cases examples",
        f"{topic} challenges solutions",
    ]

    # ── Log pipeline start ────────────────────────────────────────────────────
    print(f"✅ Supervisor: Input validated, handing to Research Agent")
    print(f"   Search queries prepared: {len(search_queries)}")

    return {
        "current_agent": "research",
        "topic": topic,   # Use the refined topic downstream
        "search_queries_used": search_queries,
        "pipeline_start_time": time.time(),
        "error": None,
        "messages": [
            HumanMessage(content=(
                f"Generate {tone} content about: {topic}\n"
                f"Platforms: {', '.join(state['target_platforms'])}\n"
                f"Additional context: {state.get('additional_context', 'None')}"
            ))
        ],
    }